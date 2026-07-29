"""
Freshservice API exploration script.

Purpose: empirically answer questions about the live Freshservice API surface
(auth, required fields, rate limits) by exercising it directly. Read-only
operations first; create-then-delete cycles last, with hard-coded safety
rails so the script cannot produce stray tickets in production.

Notes:
    - No sandbox available; this targets the live Preiss Freshservice instance.
    - Every test ticket subject is prefixed [TEST-Molli].
    - Required fields on every ticket: email, system, issue.
    - Tickets are deleted immediately after creation.

Usage:
    # one-time setup
    uv sync --all-packages

    # run everything
    FRESHSERVICE_API_KEY=<key> FRESHSERVICE_DOMAIN=<domain> \\
        uv run python scripts/explore_freshservice.py

    # or one section at a time
    FRESHSERVICE_API_KEY=<key> FRESHSERVICE_DOMAIN=<domain> \\
        uv run python scripts/explore_freshservice.py --section fields

    # to skip the write sections entirely
    FRESHSERVICE_API_KEY=<key> FRESHSERVICE_DOMAIN=<domain> \\
        uv run python scripts/explore_freshservice.py --read-only
"""

from __future__ import annotations

import argparse
import base64
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
from rich.prompt import Confirm
from rich.table import Table

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# These constants are the safety rails. Do not loosen them without thinking
# carefully about who sees the resulting tickets and how they get cleaned up.
REQUIRED_SUBJECT_PREFIX = "[TEST-Molli]"
REQUIRED_TAG = "molli-spike"

# Where dumps go
TMP_DIR = Path(__file__).parent.parent / "tmp" / "freshservice"

TIMEOUT_SECONDS = 30.0

console = Console()


# ---------------------------------------------------------------------------
# Request logging
# ---------------------------------------------------------------------------


@dataclass
class RequestLog:
    method: str
    url: str
    status: int
    duration_ms: float
    rate_limit_headers: dict[str, str] = field(default_factory=dict)


request_log: list[RequestLog] = []


def make_client() -> httpx.Client:
    """Build an httpx client with Basic Auth and the per-tenant base URL."""
    api_key = os.environ.get("FRESHSERVICE_API_KEY")
    domain = os.environ.get("FRESHSERVICE_DOMAIN")

    if not api_key:
        console.print("[red]FRESHSERVICE_API_KEY environment variable is not set.[/red]")
        sys.exit(1)
    if not domain:
        console.print("[red]FRESHSERVICE_DOMAIN environment variable is not set.[/red]")
        console.print(
            "Example: FRESHSERVICE_DOMAIN=preiss (the subdomain before .freshservice.com)"
        )
        sys.exit(1)

    # Freshservice uses HTTP Basic Auth: api_key as username, anything as password.
    # Convention is "X".
    auth_bytes = f"{api_key}:X".encode()
    auth_header = "Basic " + base64.b64encode(auth_bytes).decode()

    base_url = f"https://{domain}.freshservice.com/api/v2"

    return httpx.Client(
        base_url=base_url,
        headers={
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=TIMEOUT_SECONDS,
    )


def _log_response(method: str, response: httpx.Response, duration_ms: float) -> None:
    rate_headers = {
        k: v
        for k, v in response.headers.items()
        if "ratelimit" in k.lower() or k.lower() == "retry-after"
    }
    request_log.append(
        RequestLog(
            method=method,
            url=str(response.request.url),
            status=response.status_code,
            duration_ms=duration_ms,
            rate_limit_headers=rate_headers,
        )
    )


def get(client: httpx.Client, path: str, **params: Any) -> httpx.Response:
    start = time.perf_counter()
    response = client.get(path, params=params or None)
    _log_response("GET", response, (time.perf_counter() - start) * 1000)
    return response


def post(client: httpx.Client, path: str, json_body: dict[str, Any]) -> httpx.Response:
    """POST with safety rails. Refuses to send anything that doesn't meet
    the spike's tagging conventions."""
    subject = json_body.get("subject", "")
    if not subject.startswith(REQUIRED_SUBJECT_PREFIX):
        raise RuntimeError(
            f"Refusing to POST: subject must start with {REQUIRED_SUBJECT_PREFIX!r}. "
            f"Got: {subject!r}"
        )
    tags = json_body.get("tags", [])
    if REQUIRED_TAG not in tags:
        raise RuntimeError(f"Refusing to POST: 'tags' must include {REQUIRED_TAG!r}. Got: {tags!r}")

    start = time.perf_counter()
    response = client.post(path, json=json_body)
    _log_response("POST", response, (time.perf_counter() - start) * 1000)
    return response


def delete(client: httpx.Client, path: str) -> httpx.Response:
    start = time.perf_counter()
    response = client.delete(path)
    _log_response("DELETE", response, (time.perf_counter() - start) * 1000)
    return response


def dump_json(name: str, data: Any) -> Path:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    path = TMP_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str))
    return path


def section_header(title: str) -> None:
    console.print()
    console.print(Panel.fit(title, style="bold cyan"))


def pretty_keys(data: dict[str, Any], indent: int = 0) -> None:
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
# Section 1: connectivity
# ---------------------------------------------------------------------------


def section_1_connectivity(client: httpx.Client) -> None:
    section_header("Section 1 — Connectivity + auth")
    response = get(client, "/agents/me")

    console.print(f"Status: [bold]{response.status_code}[/bold]")
    console.print(f"Elapsed: {request_log[-1].duration_ms:.0f}ms")

    if response.status_code == 401:
        console.print("[red]401 Unauthorized — check API key and that Basic Auth is correct.[/red]")
        return
    if response.status_code == 404:
        console.print("[red]404 — FRESHSERVICE_DOMAIN is probably wrong.[/red]")
        console.print(f"  Sent base URL: {client.base_url}")
        return
    if not response.is_success:
        console.print(f"[red]Non-success: {response.status_code}[/red]")
        console.print(response.text[:500])
        return

    data = response.json()
    dump_path = dump_json("01_agents_me", data)
    console.print(f"Raw response saved: [dim]{dump_path}[/dim]")
    console.print()
    console.print("Agent record for this API key:")
    pretty_keys(data)


# ---------------------------------------------------------------------------
# Section 2: list groups
# ---------------------------------------------------------------------------


def section_2_groups(client: httpx.Client) -> dict[str, int]:
    """Returns a mapping of group_name -> group_id for downstream use."""
    section_header("Section 2 — List groups")
    response = get(client, "/groups")

    if not response.is_success:
        console.print(f"[red]{response.status_code}: {response.text[:200]}[/red]")
        return {}

    data = response.json()
    dump_json("02_groups", data)

    # Freshservice typically wraps in {"groups": [...]} — adjust if not
    groups = data.get("groups", data) if isinstance(data, dict) else data

    table = Table(title="Groups")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Description")

    name_to_id: dict[str, int] = {}
    for group in groups:
        gid = group.get("id")
        name = group.get("name", "")
        description = (group.get("description") or "")[:60]
        table.add_row(str(gid), name, description)
        if name and gid is not None:
            name_to_id[name] = gid

    console.print(table)
    console.print()
    console.print(f"Saved to [dim]{TMP_DIR}/02_groups.json[/dim]")
    return name_to_id


# ---------------------------------------------------------------------------
# Section 3: list agents
# ---------------------------------------------------------------------------


def section_3_agents(client: httpx.Client) -> None:
    section_header("Section 3 — List agents")
    response = get(client, "/agents")

    if not response.is_success:
        console.print(f"[red]{response.status_code}: {response.text[:200]}[/red]")
        return

    data = response.json()
    dump_json("03_agents", data)

    agents = data.get("agents", data) if isinstance(data, dict) else data

    console.print(f"Total agents: {len(agents)}")

    # Look for the SMEs by partial name match
    targets = ["adam", "lane", "toni", "sally"]
    table = Table(title="SME matches")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Email")

    for agent in agents:
        first = (agent.get("first_name") or "").lower()
        last = (agent.get("last_name") or "").lower()
        if any(t in first or t in last for t in targets):
            table.add_row(
                str(agent.get("id")),
                f"{agent.get('first_name')} {agent.get('last_name')}",
                agent.get("email") or "",
            )

    console.print(table)


# ---------------------------------------------------------------------------
# Section 4: ticket form fields — CRITICAL
# ---------------------------------------------------------------------------


def section_4_ticket_fields(client: httpx.Client) -> dict[str, Any]:
    """The most important read-only call. Tells us the exact custom field
    keys for System and Issue, plus their allowed values if dropdown."""
    section_header("Section 4 — Ticket form fields (CRITICAL — sets up payload structure)")

    # Path varies by plan. Try the common ones in order.
    candidates = ["/ticket_form_fields", "/ticket_fields", "/admin/ticket_fields"]

    response = None
    for path in candidates:
        console.print(f"Trying [bold]{path}[/bold]...")
        response = get(client, path)
        if response.is_success:
            console.print(f"  -> {response.status_code} OK")
            break
        console.print(f"  -> {response.status_code}")

    if response is None or not response.is_success:
        console.print("[red]Could not find a working ticket fields endpoint.[/red]")
        console.print("Check the Freshservice docs for the right path on this plan.")
        return {}

    data = response.json()
    dump_json("04_ticket_fields", data)

    fields = data.get("ticket_fields", data.get("fields", data)) if isinstance(data, dict) else data

    # Walk every field, surface the ones likely to be System and Issue
    table = Table(title="Ticket fields")
    table.add_column("Name")
    table.add_column("Label")
    table.add_column("Type")
    table.add_column("Required?")
    table.add_column("Default?")
    table.add_column("Choices")

    likely_system_keys: list[str] = []
    likely_issue_keys: list[str] = []

    for f in fields:
        name = f.get("name", "")
        label = f.get("label", "") or f.get("label_for_customers", "")
        ftype = f.get("type", "")
        required = str(f.get("required", "") or f.get("required_for_agents", ""))
        default = str(f.get("default", ""))
        choices_raw = f.get("choices") or []
        if isinstance(choices_raw, dict):
            choices_preview = ", ".join(list(choices_raw.keys())[:3])
        elif isinstance(choices_raw, list):
            choices_preview = ", ".join(str(c) for c in choices_raw[:3])
        else:
            choices_preview = ""
        if len(choices_preview) > 50:
            choices_preview = choices_preview[:47] + "..."

        table.add_row(name, label, ftype, required, default, choices_preview)

        name_lower = name.lower()
        label_lower = label.lower()
        if "system" in name_lower or "system" in label_lower:
            likely_system_keys.append(name)
        if "issue" in name_lower or "issue" in label_lower:
            likely_issue_keys.append(name)

    console.print(table)
    console.print()

    if likely_system_keys:
        console.print(f"[green]Likely 'System' field key(s): {likely_system_keys}[/green]")
    else:
        console.print("[yellow]No obvious 'System' field — search the dump manually.[/yellow]")

    if likely_issue_keys:
        console.print(f"[green]Likely 'Issue' field key(s): {likely_issue_keys}[/green]")
    else:
        console.print("[yellow]No obvious 'Issue' field — search the dump manually.[/yellow]")

    console.print()
    console.print(
        "[bold]ACTION:[/bold] use the field keys above when building the payloads in "
        "section 7. If unsure, open the dumped JSON and look at the full field "
        "definitions including required/choices."
    )

    return {
        "system_keys": likely_system_keys,
        "issue_keys": likely_issue_keys,
        "all_fields": fields,
    }


# ---------------------------------------------------------------------------
# Section 5: requester lookup
# ---------------------------------------------------------------------------


def section_5_requester_lookup(client: httpx.Client) -> None:
    section_header("Section 5 — Requester lookup by email")

    # Use the agent record from section 1 if available — that's a known-good email
    me_dump = TMP_DIR / "01_agents_me.json"
    test_email = None
    if me_dump.exists():
        me = json.loads(me_dump.read_text())
        agent = me.get("agent", me)
        test_email = agent.get("email")

    if not test_email:
        test_email = input("Enter a known Preiss email to look up: ").strip()

    # Path varies — try both
    for path_template in ["/requesters", "/contacts"]:
        console.print(f"Trying [bold]{path_template}?email={test_email}[/bold]...")
        response = get(client, path_template, email=test_email)
        if response.is_success:
            data = response.json()
            dump_json(f"05_requester_lookup_{path_template.strip('/')}", data)
            console.print(f"  -> {response.status_code}")
            results = (
                data.get("requesters")
                or data.get("contacts")
                or (data if isinstance(data, list) else [])
            )
            console.print(f"  Found {len(results)} record(s)")
            if results:
                console.print("  First record shape:")
                pretty_keys(results[0], indent=1)
            break
        console.print(f"  -> {response.status_code}")

    # Probe the no-match case
    console.print()
    console.print("Probing the no-match case with a bogus email...")
    response = get(client, path_template, email="definitely-not-real-x9z2@nowhere.invalid")
    console.print(f"  Status: {response.status_code}")
    if response.is_success:
        data = response.json()
        results = data.get("requesters") or data.get("contacts") or []
        console.print(f"  Records returned: {len(results)} (0 expected)")


# ---------------------------------------------------------------------------
# Section 6: rate limit probe
# ---------------------------------------------------------------------------


def section_6_rate_limits(client: httpx.Client, total_calls: int = 30) -> None:
    section_header(f"Section 6 — Rate limit probe ({total_calls} sequential calls to /agents/me)")

    table = Table()
    table.add_column("#")
    table.add_column("Status")
    table.add_column("ms")
    table.add_column("Headers")

    for i in range(1, total_calls + 1):
        response = get(client, "/agents/me")
        log = request_log[-1]
        headers_str = ", ".join(f"{k}={v}" for k, v in log.rate_limit_headers.items()) or "(none)"
        table.add_row(str(i), str(log.status), f"{log.duration_ms:.0f}", headers_str)

        if response.status_code == 429:
            console.print(table)
            console.print()
            retry = response.headers.get("Retry-After")
            console.print(f"[yellow]Hit 429 at call {i}. Retry-After: {retry!r}[/yellow]")
            return

    console.print(table)
    console.print()
    console.print(f"[green]No 429s in {total_calls} calls.[/green]")


# ---------------------------------------------------------------------------
# Section 7: create-and-delete cycles for the three scenarios
# ---------------------------------------------------------------------------


def build_scenario_payloads(
    requester_email: str,
    it_group_id: int | None,
    system_field_key: str,
    issue_field_key: str,
) -> list[dict[str, Any]]:
    """Build the three reference payloads using real IDs and field keys.

    The custom field keys (system_field_key, issue_field_key) come from
    section 4's discovery. If those came back empty, the caller should
    refuse to run section 7.
    """

    def cf(system_value: str, issue_value: str, **extras: Any) -> dict[str, Any]:
        # Build the custom_fields block, mapping the discovered keys to values.
        block: dict[str, Any] = {
            system_field_key: system_value,
            issue_field_key: issue_value,
        }
        block.update(extras)
        return block

    base_extras = {
        "molli_conversation_id": "spike-cycle-1",
        "molli_d360_articles_consulted": "kb-spike-test",
    }

    scenario_a = {
        "email": requester_email,
        "subject": f"{REQUIRED_SUBJECT_PREFIX} Password reset needed — self-service unavailable",
        "description": (
            "<p><strong>This is a Molli spike test ticket and will be deleted "
            "immediately after creation.</strong></p>"
            "<p>Scenario: user requested a password reset; Molli explained the "
            "self-service flow; user has no recovery email or phone.</p>"
            "<p>(In production, the full chat transcript would appear here.)</p>"
        ),
        "status": 2,
        "priority": 2,
        "source": 7,
        "tags": ["molli", REQUIRED_TAG, "scenario-a-password-reset"],
        "custom_fields": cf(
            "Google Workspace",
            "Password Reset",
            molli_confidence_score=0.85,
            molli_escalation_reason="no-confident-answer",
            **base_extras,
        ),
    }
    if it_group_id:
        scenario_a["group_id"] = it_group_id

    scenario_b = {
        "email": requester_email,
        "subject": f"{REQUIRED_SUBJECT_PREFIX} Hardware request: laptop for new hire",
        "description": (
            "<p><strong>This is a Molli spike test ticket and will be deleted "
            "immediately after creation.</strong></p>"
            "<p>Scenario: hardware request collected through chat.</p>"
            "<ul>"
            "<li>Recipient: Test Recipient</li>"
            "<li>Role: Property Manager</li>"
            "<li>Property: Test Property</li>"
            "<li>Urgency: 2 weeks</li>"
            "</ul>"
        ),
        "status": 2,
        "priority": 3,
        "source": 7,
        "tags": ["molli", REQUIRED_TAG, "scenario-b-hardware"],
        "custom_fields": cf(
            "Hardware",
            "New Request",
            molli_confidence_score=1.0,
            molli_escalation_reason="user-requested-human",
            **base_extras,
        ),
    }
    if it_group_id:
        scenario_b["group_id"] = it_group_id

    scenario_c = {
        "email": requester_email,
        "subject": f"{REQUIRED_SUBJECT_PREFIX} Unable to resolve: example uncategorized question",
        "description": (
            "<p><strong>This is a Molli spike test ticket and will be deleted "
            "immediately after creation.</strong></p>"
            "<p>Scenario: low-confidence fallback. Molli could not find a "
            "confident answer in Document360.</p>"
        ),
        "status": 2,
        "priority": 2,
        "source": 7,
        "tags": ["molli", REQUIRED_TAG, "scenario-c-triage"],
        "custom_fields": cf(
            "Other",
            "General Question",
            molli_confidence_score=0.3,
            molli_escalation_reason="no-confident-answer",
            **base_extras,
        ),
    }

    return [scenario_a, scenario_b, scenario_c]


def section_7_create_and_delete(
    client: httpx.Client,
    field_info: dict[str, Any],
    groups: dict[str, int],
    assume_yes: bool = False,
) -> None:
    section_header("Section 7 — Create + delete cycles (WRITES — run with someone watching)")

    system_keys = field_info.get("system_keys", [])
    issue_keys = field_info.get("issue_keys", [])

    if not system_keys or not issue_keys:
        console.print(
            "[red]Cannot run section 7: System or Issue field keys not discovered "
            "in section 4. Resolve that first.[/red]"
        )
        return

    # If multiple candidates surfaced, use the first one but log it.
    system_key = system_keys[0]
    issue_key = issue_keys[0]
    if len(system_keys) > 1:
        console.print(
            f"[yellow]Multiple System candidates {system_keys}; using {system_key!r}[/yellow]"
        )
    if len(issue_keys) > 1:
        console.print(
            f"[yellow]Multiple Issue candidates {issue_keys}; using {issue_key!r}[/yellow]"
        )

    # Find the IT group ID
    it_group_id = None
    for name, gid in groups.items():
        if "it" in name.lower() or "information tech" in name.lower():
            it_group_id = gid
            break
    if not it_group_id:
        console.print("[yellow]No obvious IT group found — leaving group_id unset.[/yellow]")

    # Requester email: pull from the agent record
    me_dump = TMP_DIR / "01_agents_me.json"
    if not me_dump.exists():
        console.print("[red]Run section 1 first; this section needs an agent email.[/red]")
        return
    me = json.loads(me_dump.read_text())
    agent = me.get("agent", me)
    requester_email = agent.get("email")

    payloads = build_scenario_payloads(
        requester_email=requester_email,
        it_group_id=it_group_id,
        system_field_key=system_key,
        issue_field_key=issue_key,
    )

    console.print(
        f"About to create {len(payloads)} test tickets (each tagged "
        f"{REQUIRED_TAG!r}) and delete them immediately."
    )
    console.print(f"Requester email: [bold]{requester_email}[/bold]")
    console.print()

    if (not assume_yes) and not Confirm.ask("Proceed?", default=False):
        console.print("Aborting section 7.")
        return

    for i, payload in enumerate(payloads, 1):
        console.print()
        console.print(f"[bold]Scenario {chr(64 + i)}[/bold] — {payload['subject']}")

        try:
            response = post(client, "/tickets", payload)
        except RuntimeError as e:
            console.print(f"[red]Safety rail blocked POST: {e}[/red]")
            continue

        console.print(
            f"  POST status: {response.status_code} ({request_log[-1].duration_ms:.0f}ms)"
        )

        if not response.is_success:
            console.print(f"[red]  Failure body: {response.text[:600]}[/red]")
            dump_json(
                f"07_scenario_{chr(96 + i)}_FAILURE",
                {
                    "request": payload,
                    "response_status": response.status_code,
                    "response_body": response.text,
                },
            )
            continue

        created = response.json()
        ticket = created.get("ticket", created)
        ticket_id = ticket.get("id")
        dump_json(f"07_scenario_{chr(96 + i)}_created", created)
        console.print(f"  Created ticket id: [bold]{ticket_id}[/bold]")

        # Delete immediately
        delete_response = delete(client, f"/tickets/{ticket_id}")
        console.print(f"  DELETE status: {delete_response.status_code}")
        if not delete_response.is_success:
            console.print(
                f"[red]  Delete failed. Manual cleanup needed for ticket {ticket_id}![/red]"
            )
            console.print(f"  Response: {delete_response.text[:300]}")


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
        method_style = (
            "yellow" if log.method == "POST" else ("red" if log.method == "DELETE" else "white")
        )
        table.add_row(
            str(i),
            f"[{method_style}]{log.method}[/{method_style}]",
            url,
            f"[{status_style}]{log.status}[/{status_style}]",
            f"{log.duration_ms:.0f}",
        )

    console.print(table)
    console.print()

    posts = sum(1 for r in request_log if r.method == "POST" and 200 <= r.status < 300)
    deletes = sum(1 for r in request_log if r.method == "DELETE" and 200 <= r.status < 300)
    console.print(f"Successful POSTs: {posts}, successful DELETEs: {deletes}")
    if posts != deletes:
        console.print(
            f"[red]MISMATCH: {posts} tickets created but only {deletes} deleted. "
            f"Manual cleanup required.[/red]"
        )
    else:
        console.print("[green]Create/delete pairs balanced.[/green]")

    console.print()
    console.print(f"Raw responses saved to: [dim]{TMP_DIR}[/dim]")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


SECTIONS = ["connectivity", "groups", "agents", "fields", "requester", "rate-limit", "tickets"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Freshservice API exploration script")
    parser.add_argument(
        "--section",
        choices=SECTIONS + ["all"],
        default="all",
        help="Run a single section instead of all",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Skip the ticket create+delete section (section 7)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt before creating test tickets",
    )
    args = parser.parse_args()

    console.print(
        Panel.fit(
            "[bold]Freshservice API exploration[/bold]\n"
            f"Domain: {os.environ.get('FRESHSERVICE_DOMAIN', '<unset>')}\n"
            f"Subject prefix: {REQUIRED_SUBJECT_PREFIX}\n"
            f"Required tag: {REQUIRED_TAG}\n"
            f"Output dir: {TMP_DIR}",
            style="cyan",
        )
    )

    with make_client() as client:
        groups: dict[str, int] = {}
        field_info: dict[str, Any] = {}

        if args.section in ("all", "connectivity"):
            section_1_connectivity(client)
        if args.section in ("all", "groups"):
            groups = section_2_groups(client)
        if args.section in ("all", "agents"):
            section_3_agents(client)
        if args.section in ("all", "fields"):
            field_info = section_4_ticket_fields(client)
        if args.section in ("all", "requester"):
            section_5_requester_lookup(client)
        if args.section in ("all", "rate-limit"):
            section_6_rate_limits(client)
        if args.section in ("all", "tickets") and not args.read_only:
            # Re-fetch groups and fields if we're running tickets in isolation
            if not groups:
                groups = section_2_groups(client)
            if not field_info:
                field_info = section_4_ticket_fields(client)
            section_7_create_and_delete(client, field_info, groups, assume_yes=args.yes)

    print_summary()


if __name__ == "__main__":
    main()
