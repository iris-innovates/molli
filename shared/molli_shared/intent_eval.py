"""Misroute-rate validation for the intent classifier (manual, live Gemini).

Runs a labeled set of sample queries -- drawn from the ticket audit's real
cluster examples across IT / Ops / HR plus ambiguous/general cases -- through
classify_intent and reports accuracy, misroute rate, and a confusion summary.

NOT a CI test (needs live Gemini). Run from shared:
    uv run python -m molli_shared.intent_eval

The labels are the EXPECTED department per the audit's ownership. 'general'
covers off-topic / non-Preiss queries that should NOT be force-routed.
Review/adjust labels as the audit's edge cases dictate.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from molli_shared.intent import classify_intent

# (query, expected_intent). Sourced from the ticket-audit cluster examples.
LABELED: list[tuple[str, str]] = [
    # --- IT (Google Workspace, passwords, printers, hardware, email) ---
    ("How do I reset my Google password?", "IT"),
    ("I'm locked out of my Gmail account", "IT"),
    ("How do I connect to the office printer?", "IT"),
    ("My computer can't find the printer", "IT"),
    ("Please add me to the Capex distribution list", "IT"),
    ("I need a new laptop for a new hire", "IT"),
    ("How do I connect to the VPN?", "IT"),
    ("A message is stuck in Mimecast, how do I release it?", "IT"),
    # --- Ops (Entrata, portals, leases, ledgers, screening, properties) ---
    ("How do I request access in Entrata?", "Ops"),
    ("How do I refund a payment in Entrata?", "Ops"),
    ("How do I reverse a charge on a resident ledger?", "Ops"),
    ("A resident can't log into the resident portal", "Ops"),
    ("How do I switch a guarantor mid-lease?", "Ops"),
    ("How do I correct the address on a renewal lease?", "Ops"),
    ("How do I upload the monthly utility charges?", "Ops"),
    ("How do I update office hours for a property?", "Ops"),
    # --- HR (benefits, PTO, payroll, onboarding, handbook) ---
    ("What are my benefits options?", "HR"),
    ("How much PTO do I accrue per year?", "HR"),
    ("When is the payroll cutoff this month?", "HR"),
    ("What's the onboarding checklist for a new employee?", "HR"),
    ("Where can I find the employee handbook?", "HR"),
    ("How do I request parental leave?", "HR"),
    # --- general / ambiguous (should NOT be force-routed) ---
    ("What's the capital of France?", "general"),
    ("Thanks, that's all I needed!", "general"),
    ("Can you help me?", "general"),
]


async def main() -> None:
    correct = 0
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    low_conf = 0
    rows: list[tuple[str, str, str, float, bool]] = []

    for query, expected in LABELED:
        result = await classify_intent(query)
        hit = result.intent == expected
        correct += int(hit)
        confusion[expected][result.intent] += 1
        if result.confidence < 0.5:
            low_conf += 1
        rows.append((query, expected, result.intent, result.confidence, hit))

    total = len(LABELED)
    print("=" * 80)
    for query, expected, got, conf, hit in rows:
        flag = "OK  " if hit else "MISS"
        print(f"{flag}  exp={expected:8} got={got:8} conf={conf:.2f}  {query[:48]}")

    print("=" * 80)
    print("SUMMARY")
    print(f"  total queries:   {total}")
    print(f"  correct:         {correct}")
    print(f"  accuracy:        {correct / total:.1%}")
    print(f"  MISROUTE RATE:   {(total - correct) / total:.1%}")
    print(f"  low-confidence:  {low_conf} (conf < 0.5)")
    print()
    print("  confusion (expected -> predicted counts):")
    for exp in sorted(confusion):
        preds = ", ".join(f"{k}:{v}" for k, v in sorted(confusion[exp].items()))
        print(f"    {exp:8} -> {preds}")


if __name__ == "__main__":
    asyncio.run(main())
