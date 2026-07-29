"""Reset prompt buttons appended when Molli detects a topic change.

Returns two button widget dicts compatible with answer_card.answer_message's
`actions` parameter. No dialog interaction -- clicks are handled as plain
CARD_CLICKED events (resetHistory / keepHistory).
"""

from __future__ import annotations

from typing import Any

from app.cards.dialog import SERVICE_URL

# Shown above the clear/keep buttons so the user knows why they're there.
RESET_PROMPT_MESSAGE = (
    "I've noticed the conversation has shifted to a new topic. Click below if "
    "you'd like me to clear the older context for a more focused answer."
)


def reset_prompt_actions() -> list[dict[str, Any]]:
    """Return [clear-history, keep-history] button dicts."""
    return [
        {
            "text": "Yes, clear history",
            "onClick": {
                "action": {
                    "function": SERVICE_URL,
                    "parameters": [
                        {"key": "actionName", "value": "resetHistory"},
                    ],
                }
            },
        },
        {
            "text": "No, keep it",
            "onClick": {
                "action": {
                    "function": SERVICE_URL,
                    "parameters": [
                        {"key": "actionName", "value": "keepHistory"},
                    ],
                }
            },
        },
    ]
