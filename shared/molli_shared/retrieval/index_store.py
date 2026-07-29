"""Vector index upsert + query for the sync job.

Wraps the Vertex AI Vector Search streaming upsert (proven in
scripts/spikes/vector_search_test.py) and adds the metadata-bearing datapoint
construction the sync job needs.

Datapoint id scheme: ``{article_id}::{chunk_ordinal}`` — deterministic, so
re-running the sync overwrites the same datapoints rather than duplicating
(idempotent). When an article loses chunks (e.g. it got shorter), stale
datapoints with higher ordinals are removed via ``remove_article``.

Metadata travels as ``restricts`` (filterable tokens) plus ``crowding_tag``.
Vector Search datapoints don't carry arbitrary JSON, so human-readable fields
(title, url, heading, category) are stored as namespaced restrict tokens that
chat-service can read back from neighbor results for citation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from google.api_core.exceptions import InvalidArgument
from google.cloud import aiplatform_v1

from molli_shared.vertex_retry import vertex_retry

log = structlog.get_logger()

_REGIONAL_HOST = "{region}-aiplatform.googleapis.com"

# Vector Search restrict tokens have an undocumented-but-real byte-length cap;
# a title/heading with multi-byte UTF-8 chars can blow past it well before
# hitting the [:300] *character* truncation below, causing an opaque
# INVALID_ARGUMENT on upsert. Cap by bytes, not characters, to actually stay
# under it.
_MAX_RESTRICT_BYTES = 200


def _truncate_bytes(text: str, max_bytes: int = _MAX_RESTRICT_BYTES) -> str:
    """Truncate to at most max_bytes UTF-8 bytes without splitting a char."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


@dataclass
class IndexedChunk:
    """A chunk plus its embedding and citation metadata, ready to upsert."""

    article_id: str
    ordinal: int
    vector: list[float]
    title: str
    url: str
    category_id: str
    heading: str

    @property
    def datapoint_id(self) -> str:
        return f"{self.article_id}::{self.ordinal}"


class VectorIndex:
    """Streaming upsert + nearest-neighbor query against one deployed index."""

    def __init__(
        self,
        project_id: str,
        index_id: str,
        index_endpoint_id: str,
        deployed_index_id: str,
        public_endpoint_domain: str,
        region: str = "us-central1",
    ) -> None:
        self._project = project_id
        self._region = region
        self._index_name = (
            f"projects/{project_id}/locations/{region}/indexes/{index_id}"
        )
        self._endpoint_name = (
            f"projects/{project_id}/locations/{region}"
            f"/indexEndpoints/{index_endpoint_id}"
        )
        self._deployed_index_id = deployed_index_id

        regional = _REGIONAL_HOST.format(region=region)
        self._index_client = aiplatform_v1.IndexServiceClient(
            client_options={"api_endpoint": regional}
        )
        # Queries must hit the endpoint's public domain, NOT the regional host
        # (regional host returns 501 for find_neighbors).
        self._match_client = aiplatform_v1.MatchServiceClient(
            client_options={"api_endpoint": public_endpoint_domain}
        )

    def upsert(self, chunks: list[IndexedChunk]) -> int:
        """Upsert chunks in batches. Returns the number actually upserted.

        A batch that fails with INVALID_ARGUMENT is retried one datapoint at a
        time so a single malformed chunk (e.g. a restrict token over the
        length cap) doesn't drop the whole batch -- the bad one is logged and
        skipped, everything else in the batch still gets indexed.
        """
        if not chunks:
            return 0
        # The streaming upsert accepts a generous batch; chunk at 1000 to be safe.
        total = 0
        for start in range(0, len(chunks), 1000):
            chunk_batch = chunks[start : start + 1000]
            datapoints = [self._to_datapoint(c) for c in chunk_batch]
            try:
                self._upsert_datapoints(datapoints)
                total += len(datapoints)
            except InvalidArgument:
                total += self._upsert_one_by_one(chunk_batch)
        return total

    def _upsert_one_by_one(self, chunk_batch: list[IndexedChunk]) -> int:
        """Fallback when a batch upsert is rejected: isolate the bad chunk(s).

        Returns the count that upserted successfully; logs and skips any that
        fail, instead of taking down the whole sync.
        """
        upserted = 0
        for c in chunk_batch:
            try:
                self._upsert_datapoints([self._to_datapoint(c)])
                upserted += 1
            except InvalidArgument as exc:
                log.error(
                    "upsert_datapoint_rejected",
                    article_id=c.article_id,
                    ordinal=c.ordinal,
                    title=c.title,
                    title_bytes=len(c.title.encode("utf-8")),
                    heading=c.heading,
                    heading_bytes=len(c.heading.encode("utf-8")),
                    category_id=c.category_id,
                    url=c.url,
                    vector_dims=len(c.vector),
                    error=str(exc),
                )
        return upserted

    def _upsert_datapoints(
        self, datapoints: list[aiplatform_v1.IndexDatapoint]
    ) -> None:
        self._index_client.upsert_datapoints(
            request=aiplatform_v1.UpsertDatapointsRequest(
                index=self._index_name,
                datapoints=datapoints,
            )
        )

    def remove_article(self, article_id: str, keep_ordinals: int) -> None:
        """Remove stale datapoints for an article whose chunk count shrank.

        Removes ids ``{article_id}::{n}`` for n >= keep_ordinals, up to a small
        look-ahead. Safe to call with ids that don't exist."""
        stale = [f"{article_id}::{n}" for n in range(keep_ordinals, keep_ordinals + 50)]
        self._index_client.remove_datapoints(
            request=aiplatform_v1.RemoveDatapointsRequest(
                index=self._index_name,
                datapoint_ids=stale,
            )
        )

    def _to_datapoint(self, c: IndexedChunk) -> aiplatform_v1.IndexDatapoint:
        return aiplatform_v1.IndexDatapoint(
            datapoint_id=c.datapoint_id,
            feature_vector=c.vector,
            restricts=[
                aiplatform_v1.IndexDatapoint.Restriction(
                    namespace="article_id", allow_list=[c.article_id]
                ),
                aiplatform_v1.IndexDatapoint.Restriction(
                    namespace="category_id", allow_list=[c.category_id or ""]
                ),
                aiplatform_v1.IndexDatapoint.Restriction(
                    namespace="title", allow_list=[_truncate_bytes(c.title)]
                ),
                aiplatform_v1.IndexDatapoint.Restriction(
                    namespace="url", allow_list=[c.url or ""]
                ),
                aiplatform_v1.IndexDatapoint.Restriction(
                    namespace="heading", allow_list=[_truncate_bytes(c.heading)]
                ),
            ],
            crowding_tag=aiplatform_v1.IndexDatapoint.CrowdingTag(
                crowding_attribute=c.article_id
            ),
        )

    def query(
        self, vector: list[float], neighbor_count: int = 5
    ) -> list[dict[str, Any]]:
        """Nearest-neighbor search. Returns id/distance/metadata dicts."""
        request = aiplatform_v1.FindNeighborsRequest(
            index_endpoint=self._endpoint_name,
            deployed_index_id=self._deployed_index_id,
            queries=[
                aiplatform_v1.FindNeighborsRequest.Query(
                    datapoint=aiplatform_v1.IndexDatapoint(feature_vector=vector),
                    neighbor_count=neighbor_count,
                )
            ],
            return_full_datapoint=True,
        )
        response = self._find_neighbors(request)
        results: list[dict[str, Any]] = []
        if not response.nearest_neighbors:
            return results
        for neighbor in response.nearest_neighbors[0].neighbors:
            dp = neighbor.datapoint
            meta = {
                r.namespace: list(r.allow_list)[0] if r.allow_list else ""
                for r in dp.restricts
            }
            results.append(
                {
                    "id": dp.datapoint_id,
                    "distance": neighbor.distance,
                    "title": meta.get("title", ""),
                    "url": meta.get("url", ""),
                    "heading": meta.get("heading", ""),
                    "category_id": meta.get("category_id", ""),
                }
            )
        return results

    @vertex_retry  # type: ignore[untyped-decorator]
    def _find_neighbors(
        self, request: aiplatform_v1.FindNeighborsRequest
    ) -> aiplatform_v1.FindNeighborsResponse:
        return self._match_client.find_neighbors(request=request)
