"""RAG answer pipeline: retrieve D360 chunks, ground Gemini on their text, cite.

Flow:
    query -> embed (RETRIEVAL_QUERY) -> Vector Search top-k neighbour ids
          -> ChunkStore.get_many(ids) -> actual chunk text
          -> build grounded prompt with numbered sources (text + link)
          -> Gemini generates an answer, citing inline as [1], [2] only the
             sources it actually drew from
          -> the [n] markers are parsed to filter the citation list down to
             sources actually used, then stripped so the user-facing text
             reads as plain prose -- a deduplicated citation list (title +
             D360 URL) is appended as a hyperlinked "Sources:" list

No-context handling: Vector Search always returns top-k neighbours even for an
off-topic query, so an empty result set is NOT a reliable "not covered" signal.
Instead the model is told to emit the exact token INSUFFICIENT_CONTEXT when the
retrieved sources don't actually answer the question; we detect that and set
no_context=True so the caller can fall back to a general answer.

Design choices:
- Answers ONLY from retrieved chunk text. No hallucinated Preiss policy.
- Uses settings.gemini_model (gemini-2.5-flash) -- NOT 1.5 Pro (not a valid
  Vertex model id; flash is also better for the <30s budget).
- Lazy init + broad error fallback (same pattern as gemini_client.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog
import vertexai
from molli_shared.chunk_store import ChunkStore, StoredChunk
from molli_shared.config import get_settings
from molli_shared.retrieval import Embedder, VectorIndex
from molli_shared.vertex_retry import vertex_retry
from vertexai.generative_models import GenerationConfig, GenerationResponse, GenerativeModel

log = structlog.get_logger()

_DEPLOYED_INDEX_ID = "molli_knowledge_stream"
_PUBLIC_ENDPOINT_DOMAIN = "163164439.us-central1-719635778769.vdb.vertexai.goog"

_DEFAULT_TOP_K = 5
_MAX_CHARS_PER_CHUNK = 2000

# Sentinel the model emits when the retrieved sources don't answer the question.
_INSUFFICIENT = "INSUFFICIENT_CONTEXT"

RAG_SYSTEM_INSTRUCTION = (
    "You are Molli, Preiss's AI-powered employee assistant for IT, Operations, "
    "and HR questions. Answer using ONLY the numbered sources provided in the "
    "prompt. Rules:\n"
    "1. Base your answer only on the provided source text. Do not use outside "
    "knowledge about Preiss's internal systems, policies, or people.\n"
    "2. Whenever a claim in your answer relies on a specific source, cite it "
    "inline right after that claim with a bracketed number like [1] or [2]. "
    "Only cite sources you actually drew from -- never cite a source just "
    "because it was provided, and never cite a source for a claim it doesn't "
    "support. These markers are stripped out and replaced with a linked "
    "source list automatically, so don't worry about how they read.\n"
    "3. If the provided sources do not actually answer the question, respond "
    "with EXACTLY the single token INSUFFICIENT_CONTEXT and nothing else -- no "
    "explanation, no apology, no citations. Do not fabricate.\n"
    "4. Be concise, friendly, professional. Prefer clear steps for how-tos.\n"
)

FALLBACK_MESSAGE = (
    "Sorry -- I'm having trouble answering that right now. Please try again in "
    "a moment, or submit a Freshservice ticket if it's urgent."
)

NO_CONTEXT_MESSAGE = (
    "I couldn't find anything in Preiss Central about that. You may want to "
    "submit a Freshservice ticket or check Preiss Central directly."
)


@dataclass
class Citation:
    number: int
    title: str
    url: str


@dataclass
class RagAnswer:
    text: str
    citations: list[Citation] = field(default_factory=list)
    chunks_retrieved: int = 0
    no_context: bool = False

    def formatted(self) -> str:
        """Answer text with a Sources footer of working D360 links.

        No numbering anywhere -- inline [n] markers are stripped from the
        answer body before it reaches here (see answer_with_citations), and
        each source is just its hyperlinked title.
        """
        if not self.citations:
            return self.text
        lines = [self.text, "", "Sources:"]
        for c in self.citations:
            lines.append(f"- [{c.title}]({c.url})")
        return "\n".join(lines)


_model: GenerativeModel | None = None
_embedder: Embedder | None = None
_index: VectorIndex | None = None
_store: ChunkStore | None = None


def _get_model() -> GenerativeModel:
    global _model
    if _model is None:
        settings = get_settings()
        vertexai.init(project=settings.gcp_project_id, location=settings.gcp_region)
        _model = GenerativeModel(
            model_name=settings.gemini_model,
            system_instruction=RAG_SYSTEM_INSTRUCTION,
        )
    return _model


@vertex_retry  # type: ignore[untyped-decorator]
def _generate(model: GenerativeModel, prompt: str, temperature: float) -> GenerationResponse:
    return model.generate_content(
        prompt, generation_config=GenerationConfig(temperature=temperature)
    )


def _get_retrieval() -> tuple[Embedder, VectorIndex, ChunkStore]:
    global _embedder, _index, _store
    if _embedder is None or _index is None or _store is None:
        settings = get_settings()
        _embedder = Embedder(settings.gcp_project_id, settings.gcp_region)
        _index = VectorIndex(
            project_id=settings.gcp_project_id,
            index_id=settings.vector_index_id,
            index_endpoint_id=settings.vector_index_endpoint,
            deployed_index_id=_DEPLOYED_INDEX_ID,
            public_endpoint_domain=_PUBLIC_ENDPOINT_DOMAIN,
            region=settings.gcp_region,
        )
        _store = ChunkStore(settings.gcp_project_id, settings.firestore_database)
    return _embedder, _index, _store


_CITATION_MARKER_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def _extract_cited_numbers(text: str) -> set[int]:
    """Pull the source numbers Gemini actually cited, e.g. {1, 3} from "...[1] ... [3]"."""
    numbers: set[int] = set()
    for match in _CITATION_MARKER_RE.finditer(text):
        for part in match.group(1).split(","):
            numbers.add(int(part.strip()))
    return numbers


def _strip_citation_markers(text: str) -> str:
    """Remove [n] / [n, m] markers and tidy the whitespace/punctuation left behind."""
    stripped = _CITATION_MARKER_RE.sub("", text)
    stripped = re.sub(r"[ \t]+([.,;:!?])", r"\1", stripped)
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    return stripped.strip()


def _build_prompt(
    query: str, ordered_ids: list[str], stored: dict[str, StoredChunk]
) -> tuple[str, list[Citation]]:
    """Render retrieved chunk text as numbered sources and build the prompt."""
    source_blocks: list[str] = []
    citations: list[Citation] = []
    seen_urls: set[str] = set()
    n = 0
    for dp_id in ordered_ids:
        ch = stored.get(dp_id)
        if ch is None or not ch.text.strip():
            continue
        n += 1
        label = f"{ch.title} -- {ch.heading}" if ch.heading else ch.title
        text = ch.text[:_MAX_CHARS_PER_CHUNK]
        source_blocks.append(f"[{n}] {label}\n{text}\nLink: {ch.url}")
        if ch.url and ch.url not in seen_urls:
            seen_urls.add(ch.url)
            citations.append(Citation(number=n, title=ch.title, url=ch.url))

    sources_text = "\n\n".join(source_blocks)
    prompt = (
        f"Employee question: {query}\n\n"
        f"Numbered sources from Preiss Central (Document360):\n\n"
        f"{sources_text}\n\n"
        f"Answer using only these sources, citing inline like [1] right after "
        f"any claim that depends on a specific source -- cite only sources "
        f"you actually used. If these sources do not actually answer the "
        f"question, reply with exactly {_INSUFFICIENT} and nothing else."
    )
    return prompt, citations


def answer_with_citations(
    query: str, top_k: int = _DEFAULT_TOP_K, intent: str | None = None
) -> RagAnswer:
    """Retrieve, ground on chunk text, generate. Never raises.

    Sets no_context=True when retrieval is empty OR when the model judges the
    retrieved sources insufficient (emits the INSUFFICIENT_CONTEXT sentinel).
    """
    if not query.strip():
        return RagAnswer(text=NO_CONTEXT_MESSAGE, no_context=True)

    # intent is accepted for forward-compatibility: once a D360
    # category->department map exists, retrieval will soft-boost chunks whose
    # category matches the predicted department. Until then it is unused --
    # retrieval stays unscoped so a wrong intent can't hide the right answer.

    try:
        embedder, index, store = _get_retrieval()
        vector = embedder.embed_query(query)
        neighbours = index.query(vector, neighbor_count=top_k)
    except Exception as exc:  # noqa: BLE001
        log.error("rag_retrieval_failed", error=str(exc))
        return RagAnswer(text=FALLBACK_MESSAGE)

    if not neighbours:
        log.info("rag_no_chunks", query=query)
        return RagAnswer(text=NO_CONTEXT_MESSAGE, no_context=True)

    ordered_ids = [n["id"] for n in neighbours]
    try:
        stored = store.get_many(ordered_ids)
    except Exception as exc:  # noqa: BLE001
        log.error("rag_chunk_store_failed", error=str(exc))
        return RagAnswer(text=FALLBACK_MESSAGE, chunks_retrieved=len(neighbours))

    if not stored:
        log.warning("rag_no_stored_text", ids=ordered_ids)
        return RagAnswer(text=NO_CONTEXT_MESSAGE, no_context=True, chunks_retrieved=len(neighbours))

    prompt, citations = _build_prompt(query, ordered_ids, stored)

    try:
        settings = get_settings()
        model = _get_model()
        response = _generate(model, prompt, settings.gemini_temperature)
        text = (response.text or "").strip()
        if not text:
            log.warning("rag_empty_response")
            return RagAnswer(text=FALLBACK_MESSAGE, chunks_retrieved=len(neighbours))
    except Exception as exc:  # noqa: BLE001
        log.error("rag_generation_failed", error=str(exc))
        return RagAnswer(text=FALLBACK_MESSAGE, chunks_retrieved=len(neighbours))

    # Model judged the retrieved sources insufficient -> signal no_context so
    # the caller can fall back to a general answer. Tolerate the sentinel
    # appearing alone or with stray punctuation/whitespace.
    if text.replace("*", "").strip().upper().startswith(_INSUFFICIENT):
        log.info("rag_insufficient_context", query=query)
        return RagAnswer(text=NO_CONTEXT_MESSAGE, no_context=True, chunks_retrieved=len(neighbours))

    # Keep only the sources the model actually cited inline; if it didn't tag
    # anything (prompt drift, model quirk) fall back to the full retrieved
    # set rather than showing an answer with no sources at all.
    cited_numbers = _extract_cited_numbers(text)
    final_citations = [c for c in citations if c.number in cited_numbers] or citations
    if citations and not cited_numbers:
        log.info("rag_no_inline_citations", query=query)

    return RagAnswer(
        text=_strip_citation_markers(text),
        citations=final_citations,
        chunks_retrieved=len(neighbours),
    )


def search_docs(query: str, top_k: int = 3) -> list[Citation]:
    """Return citation links for the top matching D360 docs without generating an answer.

    Used to surface relevant policy docs alongside guardrail block responses.
    Returns an empty list on any error or when retrieval is unavailable.
    """
    if not query.strip():
        return []
    try:
        embedder, index, store = _get_retrieval()
        vector = embedder.embed_query(query)
        neighbours = index.query(vector, neighbor_count=top_k)
    except Exception as exc:  # noqa: BLE001
        log.warning("doc_search_retrieval_failed", error=str(exc))
        return []

    if not neighbours:
        return []

    ordered_ids = [n["id"] for n in neighbours]
    try:
        stored = store.get_many(ordered_ids)
    except Exception as exc:  # noqa: BLE001
        log.warning("doc_search_chunk_store_failed", error=str(exc))
        return []

    citations: list[Citation] = []
    seen_urls: set[str] = set()
    for dp_id in ordered_ids:
        ch = stored.get(dp_id)
        if ch is None or not ch.url:
            continue
        if ch.url not in seen_urls:
            seen_urls.add(ch.url)
            citations.append(Citation(number=len(citations) + 1, title=ch.title, url=ch.url))
    return citations
