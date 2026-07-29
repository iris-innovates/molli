"""Card and dialog builders for the ticket-intake dialog flow.

Flow: trigger card -> open dialog -> submit -> notify.
Plain-message responses use the chatDataAction envelope (see _chat_reply in
main.py); dialog open/submit responses use the renderActions envelope.
"""

from __future__ import annotations

from typing import Any

from molli_shared.schemas.ticket import FieldConfidence, TicketDraft

from app.cards import form_options


def _val(field: FieldConfidence | None) -> Any:
    """Pull a value out of a draft's FieldConfidence wrapper.

    Returns "" when the field is absent or Molli had no proposal (value=None),
    so a text widget renders empty rather than crashing on None.value.
    """
    if field is None or field.value is None:
        return None
    return field.value


def _str_val(field: FieldConfidence | None) -> str:
    """Like _val, but stringified for widget `value` (handles int fields like
    group_id/priority). Returns "" when there's nothing to pre-fill."""
    v = _val(field)
    return "" if v is None else str(v)


SERVICE_URL = "https://molli-chat-service-719635778769.us-central1.run.app/"


def trigger_card() -> dict[str, Any]:
    """Reply to 'dialogtest': a message card with a button that opens the dialog."""
    return {
        "hostAppDataAction": {
            "chatDataAction": {
                "createMessageAction": {
                    "message": {
                        "cardsV2": [
                            {
                                "cardId": "dialogtest-trigger",
                                "card": {
                                    "sections": [
                                        {
                                            "widgets": [
                                                {
                                                    "buttonList": {
                                                        "buttons": [
                                                            {
                                                                "text": "Full draft",
                                                                "onClick": {
                                                                    "action": {
                                                                        "function": SERVICE_URL,
                                                                        "interaction": "OPEN_DIALOG",
                                                                        "parameters": [
                                                                            {
                                                                                "key": "actionName",
                                                                                "value": "openInitialDialog",
                                                                            },
                                                                            {
                                                                                "key": "draftType",
                                                                                "value": "full",
                                                                            },
                                                                        ],
                                                                    }
                                                                },
                                                            },
                                                            {
                                                                "text": "Partial draft",
                                                                "onClick": {
                                                                    "action": {
                                                                        "function": SERVICE_URL,
                                                                        "interaction": "OPEN_DIALOG",
                                                                        "parameters": [
                                                                            {
                                                                                "key": "actionName",
                                                                                "value": "openInitialDialog",
                                                                            },
                                                                            {
                                                                                "key": "draftType",
                                                                                "value": "partial",
                                                                            },
                                                                        ],
                                                                    }
                                                                },
                                                            },
                                                            {
                                                                "text": "Empty draft",
                                                                "onClick": {
                                                                    "action": {
                                                                        "function": SERVICE_URL,
                                                                        "interaction": "OPEN_DIALOG",
                                                                        "parameters": [
                                                                            {
                                                                                "key": "actionName",
                                                                                "value": "openInitialDialog",
                                                                            },
                                                                            {
                                                                                "key": "draftType",
                                                                                "value": "empty",
                                                                            },
                                                                        ],
                                                                    }
                                                                },
                                                            },
                                                            {
                                                                "text": "Entrata access",
                                                                "onClick": {
                                                                    "action": {
                                                                        "function": SERVICE_URL,
                                                                        "interaction": "OPEN_DIALOG",
                                                                        "parameters": [
                                                                            {
                                                                                "key": "actionName",
                                                                                "value": "openStructuredDialog",
                                                                            },
                                                                            {
                                                                                "key": "requestType",
                                                                                "value": "entrata_access",
                                                                            },
                                                                        ],
                                                                    }
                                                                },
                                                            },
                                                            {
                                                                "text": "Dist list change",
                                                                "onClick": {
                                                                    "action": {
                                                                        "function": SERVICE_URL,
                                                                        "interaction": "OPEN_DIALOG",
                                                                        "parameters": [
                                                                            {
                                                                                "key": "actionName",
                                                                                "value": "openStructuredDialog",
                                                                            },
                                                                            {
                                                                                "key": "requestType",
                                                                                "value": "distribution_list",
                                                                            },
                                                                        ],
                                                                    }
                                                                },
                                                            },
                                                        ]
                                                    }
                                                }
                                            ]
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                }
            }
        }
    }


def open_dialog(draft: TicketDraft) -> dict[str, Any]:
    """Response to the openInitialDialog click: push the IT issue intake dialog."""
    # Group is not shown to the user — resolved here (Molli's guess, or the
    # catch-all fallback) and threaded through as a hidden Submit parameter
    # instead of a visible widget. See form_options.FALLBACK_GROUP.
    effective_group_id = _str_val(draft.group_id) or str(form_options.FALLBACK_GROUP["id"])
    sel_system = _val(draft.original_system)
    sel_priority = _str_val(draft.priority)
    sel_locations = set(_val(draft.msf_affected_location) or [])
    sel_more_detail = _val(draft.original_more_detail)
    more_detail_items = [
        {"text": md, "value": md, "selected": md == sel_more_detail}
        for md in form_options.more_detail_options(sel_system or "")
    ]

    location_items = [
        {"text": loc, "value": loc, "selected": loc in sel_locations}
        for loc in form_options.LOCATIONS
    ]
    system_items = [
        {"text": item, "value": item, "selected": item == sel_system}
        for item in form_options.SYSTEM_ITEMS
    ]
    priority_items = [
        {"text": p["name"], "value": str(p["value"]), "selected": str(p["value"]) == sel_priority}
        for p in form_options.PRIORITIES
    ]
    return {
        "action": {
            "navigations": [
                {
                    "pushCard": {
                        "sections": [
                            {
                                "header": "Submit an IT issue",
                                "widgets": [
                                    {
                                        "textInput": {
                                            "label": "Email",
                                            "type": "SINGLE_LINE",
                                            "name": "email",
                                            "value": _str_val(draft.email),
                                        }
                                    },
                                    {
                                        "textInput": {
                                            "label": "Subject",
                                            "type": "SINGLE_LINE",
                                            "name": "subject",
                                            "value": _str_val(draft.subject),
                                        }
                                    },
                                    {
                                        "selectionInput": {
                                            "name": "affectedLocation",
                                            "label": "Most Affected Location",
                                            "type": "MULTI_SELECT",
                                            "items": location_items,
                                        }
                                    },
                                    {
                                        "selectionInput": {
                                            "name": "systemItem",
                                            "label": "System",
                                            "type": "DROPDOWN",
                                            "items": system_items,
                                        }
                                    },
                                    {
                                        "selectionInput": {
                                            "name": "moreDetail",
                                            "label": "Issue (More Detail)",
                                            "type": "DROPDOWN",
                                            "items": more_detail_items,
                                        }
                                    },
                                    {
                                        "textInput": {
                                            "label": "Computer Name",
                                            "type": "SINGLE_LINE",
                                            "name": "computerName",
                                            "value": _str_val(draft.computer_name_if_it_issue),
                                        }
                                    },
                                    {
                                        "selectionInput": {
                                            "name": "priority",
                                            "label": "Priority *",
                                            "type": "RADIO_BUTTON",
                                            "items": priority_items,
                                        }
                                    },
                                    {"divider": {}},
                                    {
                                        "textInput": {
                                            "label": "Description",
                                            "type": "MULTIPLE_LINE",
                                            "name": "description",
                                            "value": _str_val(draft.description),
                                        }
                                    },
                                    {
                                        "buttonList": {
                                            "buttons": [
                                                {
                                                    "text": "Submit",
                                                    "onClick": {
                                                        "action": {
                                                            "function": SERVICE_URL,
                                                            "parameters": [
                                                                {
                                                                    "key": "actionName",
                                                                    "value": "submitNameDialog",
                                                                },
                                                                {
                                                                    "key": "groupId",
                                                                    "value": effective_group_id,
                                                                },
                                                            ],
                                                            # Required fields — host blocks
                                                            # submit until these have values.
                                                            "requiredWidgets": [
                                                                "email",
                                                                "subject",
                                                                "affectedLocation",
                                                                "systemItem",
                                                                "priority",
                                                                "description",
                                                            ],
                                                        }
                                                    },
                                                }
                                            ]
                                        }
                                    },
                                ],
                            }
                        ]
                    }
                }
            ]
        }
    }


def submit_notification(ticket: str) -> dict[str, Any]:
    """Response to submitNameDialog: confirm via notification.

    The notification is the confirmed-correct Add-On submit response (per
    SubmitFormResponse docs). The explicit dialog-close instruction is
    included defensively since Add-On envelope behavior for EndNavigation ->
    CLOSE_DIALOG may differ from the standalone-Chat docs.
    """
    return {
        "action": {
            "navigations": [{"endNavigation": {"action": "CLOSE_DIALOG"}}],
            "notification": {"text": f"Got it — ticket created: {ticket}"},
        }
    }
