"""
Spike: Gemini 2.5 Flash function calling with a fake search_knowledge_base tool.

Demonstrates:
  - Tool schema definition via the Vertex AI SDK
  - How the SDK surfaces tool calls vs. final text responses
  - Multi-turn handling: prompt → tool call → return result → final answer
  - What happens when Gemini decides NOT to call any tool

Save to: scripts/spikes/gemini_function_calling.py

Usage:
    uv run python scripts/spikes/gemini_function_calling.py

Prerequisites:
    - google-cloud-aiplatform>=1.60 in your environment
    - gcloud auth application-default login
    - gcloud config set project molli-dev   (or your personal GCP project)
"""

import json

import vertexai
from vertexai.generative_models import (
    Content,
    FunctionDeclaration,
    GenerativeModel,
    Part,
    Tool,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ID = "molli-dev"  # or your personal GCP project ID
LOCATION = "us-central1"
MODEL = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# Fake knowledge base — hard-coded stand-in for Document360 / Vector Search
# ---------------------------------------------------------------------------
FAKE_KB: dict[str, list[dict]] = {
    "password": [
        {
            "title": "Google password reset and account recovery",
            "content": (
                "To reset your Google Workspace password: go to accounts.google.com, "
                "click 'Forgot password', and follow the recovery steps. "
                "You'll need access to your recovery email or phone. "
                "If you have no recovery options on file, submit an IT ticket."
            ),
            "source": "Preiss Central / IT / Google Account Recovery",
        }
    ],
    "printer": [
        {
            "title": "Connecting to office printers",
            "content": (
                "Windows: open Settings → Bluetooth & devices → Printers & scanners → "
                "Add a printer. Select the printer by name (e.g. CORP-PRN-01). "
                "Mac: System Settings → Printers & Scanners → + → Add Printer. "
                "If the printer doesn't appear, make sure you're on the office Wi-Fi, "
                "not the guest network."
            ),
            "source": "Preiss Central / IT / Printer Setup",
        }
    ],
    "entrata": [
        {
            "title": "Requesting Entrata access",
            "content": (
                "Submit an IT ticket with: your name, property, the Entrata role needed "
                "(e.g. Leasing Agent, Accounting), and manager approval. "
                "Provisioning typically takes 1 business day."
            ),
            "source": "Preiss Central / Operations / Entrata Access",
        }
    ],
}


def search_knowledge_base(query: str) -> list[dict]:
    """
    Fake implementation of the search_knowledge_base tool.

    A real implementation would call Vertex AI Vector Search (or pgvector)
    with the same signature. For now it does keyword matching against FAKE_KB.

    Args:
        query: The user's question or search terms.

    Returns:
        A list of result dicts, each with 'title', 'content', and 'source'.
        Returns an empty list when no relevant article is found.
    """
    query_lower = query.lower()
    for keyword, results in FAKE_KB.items():
        if keyword in query_lower:
            return results
    return []


# ---------------------------------------------------------------------------
# Tool schema — this is what Gemini sees; must match the Python function above
# ---------------------------------------------------------------------------
KB_TOOL = Tool(
    function_declarations=[
        FunctionDeclaration(
            name="search_knowledge_base",
            description=(
                "Search Preiss Central (Document360) for articles that answer "
                "an employee's question about IT, Operations, or HR policies and procedures. "
                "Call this whenever the user is asking a how-to or policy question."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query derived from the user's question.",
                    }
                },
                "required": ["query"],
            },
        )
    ]
)

SYSTEM_INSTRUCTION = (
    "You are Molli, Preiss's AI-powered employee assistant. "
    "You help employees with IT, Operations, and HR questions by searching "
    "Preiss Central for relevant articles. "
    "Always search the knowledge base before answering a how-to or policy question. "
    "Cite the source article title in your final answer. "
    "If the knowledge base returns no results, say so honestly and suggest "
    "the employee submit a Freshservice ticket."
)


# ---------------------------------------------------------------------------
# Core: one full conversation turn with tool-call handling
# ---------------------------------------------------------------------------
def ask_molli(model: GenerativeModel, user_question: str) -> None:
    """
    Run one full question through Molli's function-calling loop and print
    each stage: question → tool call args → mock result → final answer.
    """
    separator = "─" * 60
    print(f"\n{separator}")
    print(f"USER:  {user_question}")
    print(separator)

    # Turn 1: send the user message; Gemini may respond with a tool call
    history: list[Content] = []
    user_turn = Content(role="user", parts=[Part.from_text(user_question)])
    history.append(user_turn)

    response = model.generate_content(history)
    candidate = response.candidates[0]

    # Check whether Gemini chose to call a tool
    tool_call_part = None
    for part in candidate.content.parts:
        if part.function_call:
            tool_call_part = part
            break

    if tool_call_part is None:
        # Gemini decided no tool was needed — print the direct answer
        print("TOOL CALL: (none — Gemini answered directly)")
        print(f"\nFINAL ANSWER:\n{candidate.content.parts[0].text}")
        return

    # --- Tool call path ---
    fn_call = tool_call_part.function_call
    fn_name = fn_call.name
    fn_args = dict(fn_call.args)

    print(f"TOOL CALL: {fn_name}({json.dumps(fn_args)})")

    # Dispatch to the local fake implementation
    if fn_name == "search_knowledge_base":
        tool_result = search_knowledge_base(**fn_args)
    else:
        tool_result = {"error": f"Unknown function: {fn_name}"}

    print(f"TOOL RESULT: {json.dumps(tool_result, indent=2)}")

    # Turn 2: feed the tool result back so Gemini can compose the final answer
    history.append(candidate.content)  # Gemini's turn with the function_call part
    history.append(
        Content(
            role="user",
            parts=[
                Part.from_function_response(
                    name=fn_name,
                    response={"result": tool_result},
                )
            ],
        )
    )

    final_response = model.generate_content(history)
    print(f"\nFINAL ANSWER:\n{final_response.text}")


# ---------------------------------------------------------------------------
# Main: run two demo questions
# ---------------------------------------------------------------------------
def main() -> None:
    vertexai.init(project=PROJECT_ID, location=LOCATION)

    model = GenerativeModel(
        model_name=MODEL,
        tools=[KB_TOOL],
        system_instruction=SYSTEM_INSTRUCTION,
    )

    # Question 1: Gemini SHOULD call the tool (IT how-to)
    ask_molli(model, "How do I reset my Google Workspace password?")

    # Question 2: Gemini SHOULD call the tool (Ops how-to)
    ask_molli(model, "How do I request access to Entrata?")

    # Question 3: Gemini should NOT call the tool (greeting / chit-chat)
    ask_molli(model, "Hi! What can you help me with?")


if __name__ == "__main__":
    main()
