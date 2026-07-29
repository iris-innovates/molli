"""Vertex AI text embedding.

Wraps the text-embedding model so the rest of the pipeline doesn't depend on
SDK details. Produces 768-dimension vectors, matching the index created in the
vector-backend ticket (dimensions: 768, DOT_PRODUCT_DISTANCE).

Model: text-embedding-004 (768 dims). If you change the model, the index
dimensions must match or upserts will be rejected.
"""

from __future__ import annotations

from typing import Any, cast

import vertexai
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

from molli_shared.vertex_retry import vertex_retry

_MODEL_NAME = "text-embedding-004"
_EXPECTED_DIMS = 768

# Vertex caps batch size per request; 250 is the documented ceiling for this
# model. Stay under it.
_MAX_BATCH = 250

# RETRIEVAL_DOCUMENT for the stored article chunks; queries at retrieval time
# should embed with RETRIEVAL_QUERY for best results.
_TASK_TYPE = "RETRIEVAL_DOCUMENT"
_QUERY_TASK_TYPE = "RETRIEVAL_QUERY"


class Embedder:
    """Batch text embedder over Vertex AI."""

    def __init__(self, project_id: str, region: str = "us-central1") -> None:
        vertexai.init(project=project_id, location=region)
        self._model = TextEmbeddingModel.from_pretrained(_MODEL_NAME)

    def embed(self, texts: list[str], *, title: str | None = None) -> list[list[float]]:
        """Embed a list of texts, returning one 768-d vector each.

        Batches internally to respect the per-request cap. Order is preserved.
        """
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _MAX_BATCH):
            batch = texts[start : start + _MAX_BATCH]
            inputs = [
                TextEmbeddingInput(text=t, task_type=_TASK_TYPE, title=title)
                for t in batch
            ]
            results = self._get_embeddings(inputs)
            for r in results:
                if len(r.values) != _EXPECTED_DIMS:
                    raise ValueError(
                        f"Embedding dim {len(r.values)} != expected {_EXPECTED_DIMS}. "
                        "Index dimensions and model must match."
                    )
                vectors.append(list(r.values))
        return vectors

    @vertex_retry  # type: ignore[untyped-decorator]
    def _get_embeddings(self, inputs: list[TextEmbeddingInput]) -> list[Any]:
        return self._model.get_embeddings(cast(list[str | TextEmbeddingInput], inputs))

    def embed_query(self, text: str) -> list[float]:
        """Embed a single user query for retrieval.

        Uses RETRIEVAL_QUERY task type (not RETRIEVAL_DOCUMENT), which matches
        question-shaped text against indexed document chunks far better. Indexed
        chunks are embedded with embed() / RETRIEVAL_DOCUMENT; queries must use
        this method for correct ranking.
        """
        result = self._get_embeddings(
            [TextEmbeddingInput(text=text, task_type=_QUERY_TASK_TYPE)]
        )
        values = list(result[0].values)
        if len(values) != _EXPECTED_DIMS:
            raise ValueError(
                f"Embedding dim {len(values)} != expected {_EXPECTED_DIMS}. "
                "Index dimensions and model must match."
            )
        return values
