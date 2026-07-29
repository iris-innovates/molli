"""Deterministic intro/capabilities reply for greeting and "who are you"
style messages.

This short-circuits before the guardrail chain and RAG pipeline: it's a
static string that echoes no user input and calls no model, so there's
nothing to guard against and no reason to pay for an LLM round trip.
"""

from __future__ import annotations

# Sent verbatim as the Chat API "text" field (see _chat_reply in main.py),
# which renders Google Chat's native formatting, not Markdown -- single
# asterisks for *bold*, underscores for _italic_, and "-" for bullets.
MOLLI_INTRO_MESSAGE = (
    "Hi, I'm *Molli* — Preiss's AI assistant here in Google Chat.\n\n"
    "I answer *IT*, *Operations*, and *HR* questions using articles from "
    "Preiss Central (our Document360 knowledge base). For example:\n"
    '- _IT:_ "How do I reset my Google password?"\n'
    '- _Operations:_ "How do I request access in Entrata?"\n'
    '- _HR:_ "How much PTO do I accrue?"\n\n'
    "If I can't find an answer, I can help open a Freshservice ticket so a "
    "person can follow up. What can I help you with?"
)

# Whole-message greeting/help tokens -- these are common words that also show
# up inside real questions ("help me...", "who do I contact for help..."), so
# they only count as an intro match when they make up essentially the whole
# message (see the token-count guard in is_intro_query).
_SHORT_TOKENS = {"hi", "hello", "hey", "help", "/help"}

# Full phrases that are unambiguous even if longer than two tokens.
_PHRASES = {
    "who are you",
    "what are you",
    "what can you do",
    "what do you do",
    "what can molli do",
    "who is molli",
    "what is molli",
    "how can you help",
    "what can you help with",
    "how do you work",
    "what can i ask you",
}

_STRIP_CHARS = " \t\r\n.,!?'\""


def is_intro_query(text: str) -> bool:
    """True if `text` is a greeting or an identity/capability question.

    Deliberately narrow: real questions that merely contain a trigger word
    ("help me refund a payment in Entrata") must not match. Short tokens
    ("hi", "help", ...) only match when they make up essentially the whole
    message; longer phrases are matched as complete, normalized strings.
    """
    normalized = text.strip().strip(_STRIP_CHARS).lower().strip()
    if not normalized:
        return False

    if normalized in _PHRASES:
        return True

    if normalized in _SHORT_TOKENS:
        return True

    tokens = normalized.split()
    return len(tokens) <= 2 and all(tok.strip(_STRIP_CHARS) in _SHORT_TOKENS for tok in tokens)
