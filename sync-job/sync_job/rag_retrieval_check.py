"""
RAG retrieval-quality check.

Runs known employee questions — the top D360 article needs from the ticket
audit — through the live retrieval path (embed_query -> Vector Search) and
prints top-k chunks per question, so a human can eyeball whether the right
article surfaces. A manual judgment-call check, not an automated eval.

Run from the sync-job directory:
    uv run python -m sync_job.rag_retrieval_check
"""

from __future__ import annotations

from molli_shared.config import get_settings

from sync_job.embedding import Embedder
from sync_job.index_store import VectorIndex

_DEPLOYED_INDEX_ID = "molli_knowledge_stream"
_PUBLIC_ENDPOINT_DOMAIN = "163164439.us-central1-719635778769.vdb.vertexai.goog"

# (question, what a good hit looks like) — from the ticket audit top article needs
QUESTIONS = [
    (
        "How do I reset my Google password?",
        "Google password reset / account recovery (IT, highest-impact)",
    ),
    ("How do I connect to the office printer?", "Connecting to office printers (IT)"),
    ("How do I request access in Entrata?", "Entrata: requesting access (Ops)"),
    (
        "How do I process a refund or reversal in Entrata?",
        "Entrata: refunds, reversals, scheduled charges (Ops)",
    ),
    (
        "A resident cannot log into the resident portal, what do I do?",
        "Resident portal troubleshooting (Ops)",
    ),
]

NEIGHBORS = 5


def main() -> None:
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

    for question, expected in QUESTIONS:
        print("=" * 80)
        print(f"Q: {question}")
        print(f"   expecting: {expected}")
        print("-" * 80)
        vector = embedder.embed_query(question)
        results = index.query(vector, neighbor_count=NEIGHBORS)
        if not results:
            print("   NO RESULTS")
            print()
            continue
        for i, r in enumerate(results, 1):
            section = f"  [section: {r['heading']}]" if r["heading"] else ""
            print(f"{i}. {r['title']}{section}  (distance={r['distance']:.4f})")
            print(f"   {r['url']}")
            print(f"   id={r['id']}")
        print()


if __name__ == "__main__":
    main()
