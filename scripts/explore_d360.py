"""
Document360 API exploration script.

Purpose: empirically answer questions about the live Document360 API surface
(auth, pagination, rate limits) by exercising it directly.

Usage:
    # one-time setup (from repo root, if not already done)
    uv sync --all-packages

    # run it
    D360_API_KEY=<key> uv run python scripts/explore_d360.py

    # or just one section
    D360_API_KEY=<key> uv run python scripts/explore_d360.py --section pagination

Notes:
    - This is a SPIKE script, not production code. It prints generously,
      dumps raw responses to tmp/, and prefers clarity over cleverness.
    - The real Document360 client lives at shared/molli_shared/clients/document360.py.
      That file should be rewritten using whatever this script teaches us.
    - Rate-limit probe (section 5) deliberately hammers the API. Run it last
      and only once. Skip with --skip-rate-limit if you're iterating.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Confirm these against the live docs before Monday — the v2 hub URL and
# header name are the two things most likely to differ from assumption.
BASE_URL = "https://apihub.document360.io/v2"
AUTH_HEADER_NAME = "api_token"  # candidates: "api_token" | "Authorization" | "X-API-Key"

# Where to drop raw JSON responses for inspection
TMP_DIR = Path(__file__).parent.parent / "tmp" / "d360"

# Sane defaults for all requests
TIMEOUT_SECONDS = 30.0
DEFAULT_PAGE_SIZE = 10  # small on purpose, to force multi-page traversal

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class RequestLog:
    """One row of the request log — what we hit, what we got, how long it took."""

    method: str
    url: str
    status: int
    duration_ms: float
    rate_limit_headers: dict[str, str] = field(default_factory=dict)


request_log: list[RequestLog] = []


def make_client() -> httpx.Client:
    """Build an httpx client with the auth header and a sensible timeout."""
    api_key = os.environ.get("D360_API_KEY")
    if not api_key:
        console.print("[red]D360_API_KEY environment variable is not set.[/red]")
        console.print("Run: D360_API_KEY=<key> uv run python scripts/explore_d360.py")
        sys.exit(1)

    return httpx.Client(
        base_url=BASE_URL,
        headers={AUTH_HEADER_NAME: api_key, "Accept": "application/json"},
        timeout=TIMEOUT_SECONDS,
    )


def get(client: httpx.Client, path: str, **params: Any) -> httpx.Response:
    """GET wrapper that times the request and logs rate-limit headers."""
    start = time.perf_counter()
    response = client.get(path, params=params or None)
    duration_ms = (time.perf_counter() - start) * 1000

    rate_headers = {
        k: v
        for k, v in response.headers.items()
        if "ratelimit" in k.lower() or k.lower() in ("retry-after", "x-rate-limit")
    }

    request_log.append(
        RequestLog(
            method="GET",
            url=str(response.request.url),
            status=response.status_code,
            duration_ms=duration_ms,
            rate_limit_headers=rate_headers,
        )
    )

    return response


def dump_json(name: str, data: Any) -> Path:
    """Save a raw response to tmp/d360/ for later inspection."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    path = TMP_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str))
    return path


def section_header(title: str) -> None:
    console.print()
    console.print(Panel.fit(title, style="bold cyan"))


def pretty_keys(data: dict[str, Any], indent: int = 0) -> None:
    """Print a dict's top-level keys and their value types — for figuring
    out response shape without flooding the terminal with content."""
    for key, value in data.items():
        type_name = type(value).__name__
        if isinstance(value, list) and value:
            type_name = f"list[{type(value[0]).__name__}] (len={len(value)})"
        elif isinstance(value, dict):
            type_name = f"dict (keys={list(value.keys())})"
        elif isinstance(value, str) and len(value) > 60:
            type_name = f"str (len={len(value)})"
        console.print(f"{'  ' * indent}[dim]{key}[/dim]: {type_name}")


# ---------------------------------------------------------------------------
# Section 1: connectivity + auth
# ---------------------------------------------------------------------------


def section_1_connectivity(client: httpx.Client) -> None:
    """Confirm the API key works and surface the category tree shape."""
    section_header("Section 1 — Connectivity + auth")

    # Adjust the path if docs say otherwise — categories is a common entry point
    # because it's small, fast, and confirms both auth and JSON parsing.
    response = get(client, "/categories")

    console.print(f"Status: [bold]{response.status_code}[/bold]")
    console.print(f"Elapsed: {request_log[-1].duration_ms:.0f}ms")

    if response.status_code == 401:
        console.print(
            "[red]401 Unauthorized — header name or key is wrong. "
            f"Currently sending header: {AUTH_HEADER_NAME!r}[/red]"
        )
        console.print(
            "Try changing AUTH_HEADER_NAME at the top of this file to "
            "'Authorization' (with 'Bearer ' prefix on the value) or 'X-API-Key'."
        )
        return

    if not response.is_success:
        console.print(f"[red]Non-success: {response.status_code}[/red]")
        console.print(response.text[:500])
        return

    data = response.json()
    dump_path = dump_json("01_categories", data)
    console.print(f"Raw response saved: [dim]{dump_path}[/dim]")
    console.print()
    console.print("Top-level response shape:")
    if isinstance(data, dict):
        pretty_keys(data)
    elif isinstance(data, list):
        console.print(f"  list of {len(data)} items")
        if data:
            console.print("  first item shape:")
            pretty_keys(data[0], indent=1)


# ---------------------------------------------------------------------------
# Section 2: pagination
# ---------------------------------------------------------------------------


def section_2_pagination(client: httpx.Client) -> None:
    """Walk all articles with a small page size to force multiple pages.

    Things we want to learn:
        - Is it page/page_size, offset/limit, or cursor-based?
        - What does the response include to signal "more pages"?
        - What happens past the last page?
        - Is ordering stable?
    """
    section_header("Section 2 — Pagination across 50+ articles")

    all_articles: list[dict[str, Any]] = []
    page = 1
    seen_ids: set[Any] = set()
    duplicates = 0

    while True:
        # The exact parameter names here are a guess — adjust to whatever the
        # docs specify. Common patterns: page+page_size, offset+limit, cursor.
        response = get(client, "/articles", page=page, page_size=DEFAULT_PAGE_SIZE)

        if not response.is_success:
            console.print(f"[red]Page {page} failed: {response.status_code}[/red]")
            console.print(response.text[:500])
            break

        data = response.json()

        if page == 1:
            dump_json("02_articles_page_1", data)
            console.print("First page response shape:")
            if isinstance(data, dict):
                pretty_keys(data)
            console.print()

        # Extract the article list — adjust the key name once you see the response
        # Likely candidates: "data", "articles", "items", "results"
        articles = (
            data.get("data") or data.get("articles") or data.get("items") or []
            if isinstance(data, dict)
            else data
        )

        if not articles:
            console.print(f"Page {page}: empty — assuming end of pagination.")
            break

        for article in articles:
            article_id = article.get("id")
            if article_id in seen_ids:
                duplicates += 1
            seen_ids.add(article_id)
            all_articles.append(article)

        console.print(f"Page {page}: {len(articles)} articles (total so far: {len(all_articles)})")

        # Defensive: stop after 20 pages no matter what. If the corpus is bigger
        # than that, raise the limit deliberately — don't let a runaway loop
        # burn through the API quota.
        if page >= 20:
            console.print("[yellow]Stopping at page 20 — raise the cap if needed.[/yellow]")
            break

        # Termination heuristics — confirm against the live response shape.
        # If the API returns a total_pages or is_last_page flag, use it instead.
        if len(articles) < DEFAULT_PAGE_SIZE:
            console.print("Last page reached (partial page).")
            break

        page += 1

    console.print()
    console.print(f"Total articles fetched: [bold]{len(all_articles)}[/bold]")
    console.print(f"Unique IDs: [bold]{len(seen_ids)}[/bold]")
    if duplicates:
        console.print(f"[yellow]Duplicates across pages: {duplicates}[/yellow]")
        console.print("[yellow]Ordering may not be stable — investigate.[/yellow]")

    dump_json(
        "02_all_articles_summary",
        [
            {"id": a.get("id"), "title": a.get("title"), "modified_at": a.get("modified_at")}
            for a in all_articles
        ],
    )

    # Probe what happens past the last page
    console.print()
    console.print("Probing behavior past the last page...")
    past_response = get(client, "/articles", page=999, page_size=DEFAULT_PAGE_SIZE)
    console.print(f"  Status: {past_response.status_code}")
    if past_response.is_success:
        past_data = past_response.json()
        past_articles = (
            past_data.get("data") or past_data.get("articles") or past_data.get("items") or []
            if isinstance(past_data, dict)
            else past_data
        )
        console.print(f"  Returned: {len(past_articles)} articles (expected 0)")


# ---------------------------------------------------------------------------
# Section 3: content format
# ---------------------------------------------------------------------------


def section_3_content_format(client: httpx.Client, sample_ids: list[str] | None = None) -> None:
    """Fetch full content for a few articles and inspect what we get back.

    Want to know: HTML vs Markdown? Image handling? Code block format?
    Internal links? Metadata fields?
    """
    section_header("Section 3 — Content format inspection")

    if not sample_ids:
        # Pull a few IDs from the first page if not supplied
        response = get(client, "/articles", page=1, page_size=5)
        if not response.is_success:
            console.print("[red]Could not fetch sample IDs.[/red]")
            return
        data = response.json()
        articles = (
            data.get("data") or data.get("articles") or data.get("items") or []
            if isinstance(data, dict)
            else data
        )
        sample_ids = [str(a.get("id")) for a in articles[:3] if a.get("id")]

    if not sample_ids:
        console.print("[red]No sample article IDs available.[/red]")
        return

    console.print(f"Inspecting articles: {sample_ids}")
    console.print()

    for article_id in sample_ids:
        response = get(client, f"/articles/{article_id}")

        if not response.is_success:
            console.print(f"[red]Article {article_id}: {response.status_code}[/red]")
            continue

        article = response.json()
        # D360 sometimes wraps the article in a "data" envelope — unwrap if so
        if isinstance(article, dict) and "data" in article and isinstance(article["data"], dict):
            article = article["data"]

        dump_path = dump_json(f"03_article_{article_id}", article)

        console.print(f"[bold]Article {article_id}[/bold]")
        console.print(f"  Title: {article.get('title')!r}")
        console.print(f"  Saved: [dim]{dump_path}[/dim]")
        console.print("  Top-level fields:")
        if isinstance(article, dict):
            pretty_keys(article, indent=1)

        # Heuristic content-format detection
        content = article.get("content") or article.get("html_content") or article.get("body") or ""
        if isinstance(content, str):
            console.print()
            looks_html = "<" in content and ">" in content
            looks_md = "##" in content or "```" in content or content.startswith("#")
            console.print(f"  Content length: {len(content)} chars")
            console.print(f"  Looks like HTML: {looks_html}")
            console.print(f"  Looks like Markdown: {looks_md}")
            console.print(f"  Contains <img>: {'<img' in content}")
            console.print(f"  Contains <code>/```: {'<code' in content or '```' in content}")
            console.print(f"  Contains <table>: {'<table' in content}")
        console.print()


# ---------------------------------------------------------------------------
# Section 4: modified_at filtering — the critical one
# ---------------------------------------------------------------------------


def section_4_modified_filter(client: httpx.Client) -> None:
    """Try to filter articles by modification time. This is the single most
    important question for the sync job's design."""
    section_header("Section 4 — Filter by modified_at (CRITICAL for sync design)")

    # Try a few common parameter names. Whichever returns a sensible filtered
    # response wins; the others should be ignored by the server or 400.
    candidates = ["modified_since", "updated_after", "modified_after", "since", "updated_since"]
    yesterday_iso = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(time.time() - 86400))

    results: dict[str, dict[str, Any]] = {}

    for param in candidates:
        console.print(f"Trying [bold]?{param}={yesterday_iso}[/bold]...")
        response = get(client, "/articles", **{param: yesterday_iso, "page_size": 50})
        results[param] = {
            "status": response.status_code,
            "count": None,
        }

        if response.is_success:
            data = response.json()
            articles = (
                data.get("data") or data.get("articles") or data.get("items") or []
                if isinstance(data, dict)
                else data
            )
            results[param]["count"] = len(articles)
            console.print(f"  -> {response.status_code}, {len(articles)} articles returned")
        else:
            console.print(f"  -> {response.status_code} ({response.text[:120]})")

    # Now compare against an unfiltered call to see if the count actually changed.
    # If filter is supported, count should be < total. If unsupported, the server
    # likely ignored the param and returned the full corpus.
    console.print()
    console.print("Comparison call with no filter:")
    response = get(client, "/articles", page_size=50)
    if response.is_success:
        data = response.json()
        articles = (
            data.get("data") or data.get("articles") or data.get("items") or []
            if isinstance(data, dict)
            else data
        )
        baseline = len(articles)
        console.print(f"  Baseline (no filter): {baseline} articles")
        console.print()
        table = Table(title="Filter parameter results")
        table.add_column("Parameter")
        table.add_column("Status")
        table.add_column("Count returned")
        table.add_column("Filtered?")
        for param, result in results.items():
            count = result["count"]
            filtered = "yes" if (count is not None and count < baseline) else "no/unclear"
            table.add_row(param, str(result["status"]), str(count), filtered)
        console.print(table)

    dump_json("04_modified_filter_results", results)


# ---------------------------------------------------------------------------
# Section 5: rate-limit probe
# ---------------------------------------------------------------------------


def section_5_rate_limit_probe(client: httpx.Client, total_calls: int = 30) -> None:
    """Fire requests in a tight loop and watch the rate-limit headers move.

    Deliberately hammers the API. Run this LAST and only once per spike session.
    """
    section_header(f"Section 5 — Rate limit probe ({total_calls} sequential calls)")

    table = Table()
    table.add_column("#")
    table.add_column("Status")
    table.add_column("ms")
    table.add_column("Headers")

    for i in range(1, total_calls + 1):
        response = get(client, "/articles", page=1, page_size=1)
        log = request_log[-1]
        headers_str = ", ".join(f"{k}={v}" for k, v in log.rate_limit_headers.items()) or "(none)"
        table.add_row(str(i), str(log.status), f"{log.duration_ms:.0f}", headers_str)

        if response.status_code == 429:
            console.print(table)
            console.print()
            console.print(
                f"[yellow]Hit 429 at call {i}."
                f"Retry-After: {response.headers.get('Retry-After')!r}[/yellow]"
            )
            return

    console.print(table)
    console.print()
    console.print(f"[green]No 429s hit in {total_calls} calls.[/green]")
    console.print("Either the limit is very generous, or it's measured over a longer window.")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_summary() -> None:
    section_header("Summary — all requests this session")
    table = Table()
    table.add_column("#")
    table.add_column("Method")
    table.add_column("URL (truncated)")
    table.add_column("Status")
    table.add_column("ms")

    for i, log in enumerate(request_log, 1):
        url = log.url
        if len(url) > 80:
            url = url[:77] + "..."
        status_style = "green" if 200 <= log.status < 300 else "red"
        table.add_row(
            str(i),
            log.method,
            url,
            f"[{status_style}]{log.status}[/{status_style}]",
            f"{log.duration_ms:.0f}",
        )

    console.print(table)
    console.print()
    console.print(f"Total requests: {len(request_log)}")
    console.print(f"Raw responses saved to: [dim]{TMP_DIR}[/dim]")
    console.print()
    console.print("Next: read the dumps, fill in docs/spikes/document360-api.md, open PR.")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


SECTIONS = {
    "connectivity": section_1_connectivity,
    "pagination": section_2_pagination,
    "content": section_3_content_format,
    "modified": section_4_modified_filter,
    "rate-limit": section_5_rate_limit_probe,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Document360 API exploration script")
    parser.add_argument(
        "--section",
        choices=list(SECTIONS.keys()) + ["all"],
        default="all",
        help="Run a single section instead of all of them",
    )
    parser.add_argument(
        "--skip-rate-limit",
        action="store_true",
        help="Skip section 5 (the rate-limit probe). Useful while iterating.",
    )
    args = parser.parse_args()

    console.print(
        Panel.fit(
            "[bold]Document360 API exploration[/bold]\n"
            f"Base URL: {BASE_URL}\n"
            f"Auth header: {AUTH_HEADER_NAME}\n"
            f"Output dir: {TMP_DIR}",
            style="cyan",
        )
    )

    with make_client() as client:
        if args.section == "all":
            section_1_connectivity(client)
            section_2_pagination(client)
            section_3_content_format(client)
            section_4_modified_filter(client)
            if not args.skip_rate_limit:
                section_5_rate_limit_probe(client)
        else:
            SECTIONS[args.section](client)

    print_summary()


if __name__ == "__main__":
    main()
