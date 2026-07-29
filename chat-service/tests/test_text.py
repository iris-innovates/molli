"""Unit tests for the Markdown -> Chat HTML conversion, focused on how
source links render: plain hyperlinks, no citation numbering involved.
"""

from __future__ import annotations

from app.cards.text import md_to_chat_html


def test_markdown_link_becomes_anchor() -> None:
    out = md_to_chat_html("Reset your password from the [login page](https://x/y).")
    assert '<a href="https://x/y">login page</a>' in out


def test_untrusted_scheme_link_rendered_as_plain_text() -> None:
    out = md_to_chat_html("See [here](javascript:alert(1)) for details.")
    assert "<a" not in out
    assert "here" in out


def test_sources_footer_renders_as_bulleted_links() -> None:
    out = md_to_chat_html(
        "Here's how to reset your password.\n\nSources:\n- [Password Reset](https://x/y)"
    )
    assert '<a href="https://x/y">Password Reset</a>' in out
    assert "•" in out
    # No leftover bracketed numbering anywhere.
    assert "[1]" not in out


def test_consecutive_bullets_join_tightly() -> None:
    # Chat renders a bare "\n" and a single "<br>" identically, so a tight
    # (no blank-line) list just needs a single <br> between bullets to avoid
    # the double-gap that "<br><br>" would produce.
    out = md_to_chat_html(
        "Sources:\n- [Source A](https://x/a)\n- [Source B](https://x/b)\n- [Source C](https://x/c)"
    )
    assert "Sources:<br>• " in out
    assert '<a href="https://x/a">Source A</a><br>• <a href="https://x/b">Source B</a>' in out
    assert '<a href="https://x/b">Source B</a><br>• <a href="https://x/c">Source C</a>' in out


def test_loose_bullets_drop_blank_line_before_list_item() -> None:
    # Gemini sometimes emits "loose" lists with a blank line between items.
    # The blank line immediately before a bullet is dropped so loose and
    # tight lists render identically (no double gap).
    out = md_to_chat_html("Sources:\n\n- [Source A](https://x/a)\n\n- [Source B](https://x/b)")
    assert '<a href="https://x/a">Source A</a><br>• <a href="https://x/b">Source B</a>' in out


def test_paragraph_then_bullets_keeps_br_into_list() -> None:
    out = md_to_chat_html("Intro paragraph.\n\nSources:\n- [Source A](https://x/a)")
    assert "Intro paragraph.<br><br>Sources:<br>• " in out
