"""Query the live index with a real question and print the matching chunks.

Run AFTER a sync has populated the index, to sanity-check that a test query
against the index returns relevant chunks for a known topic.

    uv run python -m sync_job.query_test "how do I reset my password"
"""

from __future__ import annotations

import sys

from molli_shared.config import get_settings

from sync_job.embedding import Embedder
from sync_job.index_store import VectorIndex

_DEPLOYED_INDEX_ID = "molli_knowledge_stream"
_PUBLIC_ENDPOINT_DOMAIN = "163164439.us-central1-719635778769.vdb.vertexai.goog"


def main() -> None:
    query = " ".join(sys.argv[1:]) or "how do I reset my password"
    settings = get_settings()

    embedder = Embedder(settings.gcp_project_id, settings.gcp_region)
    index = VectorIndex(
        project_id=settings.gcp_project_id,
        index_id=settings.vector_index_id,
        index_endpoint_id=settings.vector_index_endpoint,
        deployed_index_id=_DEPLOYED_INDEX_ID,
        public_endpoint_domain=_PUBLIC_ENDPOINT_DOMAIN,
        region=settings.gcp_region,
    )

    vector = embedder.embed_query(query)
    results = index.query(vector, neighbor_count=5)

    print(f'\nQuery: "{query}"\n')
    if not results:
        print("No results — has the sync run yet?")
        return
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['title']}  (distance={r['distance']:.4f})")
        if r["heading"]:
            print(f"   section: {r['heading']}")
        if r["url"]:
            print(f"   {r['url']}")
        print(f"   id={r['id']}")
        print()


if __name__ == "__main__":
    main()
