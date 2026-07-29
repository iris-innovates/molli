"""Builders for Google Chat ``cardsV2`` message responses.

Right now there is one builder, :func:`answer_card`, used for normal Molli
replies. It deliberately takes optional ``citations`` and ``actions`` params
that are unused today so the signature is stable when we wire those up — the
content drives which sections render, so a bare reply and a reply-with-sources
go through the same code path.

Envelope note: this returns the body for a *new message* response. Updating an
existing card in place (e.g. an answer card becoming a ticket-confirmation
card) uses a different shape — ``actionResponse`` with ``UPDATE_MESSAGE`` —
which is not handled here. Add that when the ticket button lands.
"""

from __future__ import annotations

from typing import Any

from .text import md_to_chat_html  # adjust import to match your package layout

__all__ = ["answer_card", "answer_message"]
# A stable card id lets us target this card for in-place updates later.
_ANSWER_CARD_ID = "molli_answer"


def answer_card(
    markdown_text: str,
    *,
    citations: list[dict[str, str]] | None = None,
    actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a single ``cardsV2`` entry for a Molli reply.

    Args:
        markdown_text: Gemini's answer, in Markdown. Converted to the Chat
            HTML subset before going into the card. When the answer has
            sources, ``markdown_text`` already includes a trailing "Sources:"
            list of Markdown links (see ``RagAnswer.formatted()``), which
            renders as clickable links with no numbering.
        citations: Reserved. When provided later, each item like
            ``{"title": ..., "url": ...}`` becomes a source link section.
        actions: Reserved. When provided later, each item describes a button
            (e.g. the "Create ticket" action).

    Returns:
        One element suitable for the ``cardsV2`` list of a Chat message.
    """
    html = md_to_chat_html(markdown_text)
    widgets: list[dict[str, Any]] = [{"textParagraph": {"text": html}}]

    # --- Reserved for later; content-driven so the path stays single. ---
    if citations:
        widgets.append({"divider": {}})
        for c in citations:
            title = c.get("title", "Source")
            url = c.get("url", "")
            link = f'<a href="{url}">{title}</a>' if url else title
            widgets.append({"textParagraph": {"text": f"📄 {link}"}})

    if actions:
        widgets.append(
            {
                "buttonList": {
                    "buttons": [
                        {
                            "text": a["text"],
                            "onClick": a["onClick"],
                        }
                        for a in actions
                    ]
                }
            }
        )
    # -------------------------------------------------------------------

    return {
        "cardId": _ANSWER_CARD_ID,
        "card": {"sections": [{"widgets": widgets}]},
    }


def answer_message(
    markdown_text: str,
    *,
    citations: list[dict[str, str]] | None = None,
    actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Wrap :func:`answer_card` in a full message response body.

    This is what the ``POST /`` handler returns for a normal reply instead of
    ``{"text": ...}``.

    Uses the same message envelope as ``trigger_card`` —
    ``hostAppDataAction`` -> ``chatDataAction`` -> ``createMessageAction`` —
    which is the shape confirmed to render in this app. (Distinct from the
    flat ``actionResponse`` / ``DIALOG`` shape used for dialog responses.)
    """
    return {
        "hostAppDataAction": {
            "chatDataAction": {
                "createMessageAction": {
                    "message": {
                        "cardsV2": [
                            answer_card(
                                markdown_text,
                                citations=citations,
                                actions=actions,
                            )
                        ]
                    }
                }
            }
        }
    }
