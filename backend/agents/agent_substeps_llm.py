#!/usr/bin/env python3
"""
agent_substeps_llm.py

Generate UI-level substeps for a single resolution step by calling an LLM
via Amazon Bedrock using the strands Agent.

Behavior:
 - If a `search_tickets` tool is importable (from agent_service.py) it will be
   registered with the Agent so the model can call it to fetch supporting tickets.
 - The agent is instructed to return VALID JSON only (no extra text).
 - The JSON schema returned:
   {
     "originalStep": "<input step>",
     "recommendedSubsteps": [
       {
         "id": 1,
         "title": "Open Settings",
         "step": "Open the Start menu and click Settings",
         "whereToGo": "Windows: Start > Settings > Accounts\nMac: Apple menu > System Settings > Users & Groups",
         "commands": ["powershell: Get-ADUser -Identity <user>"],
         "notes": "Requires admin privileges"
       },
       ...
     ],
     "sources": [ ... optional tool results ... ]
   }

Requirements:
 - AWS credentials must be available to the runtime (env profile, IAM role, or env vars).
 - Install dependencies for strands and Bedrock: `pip install strands opensearch-py requests-aws4auth boto3`
   (adjust to your environment; your existing project already depends on these).
 - Set optional environment vars: BEDROCK_MODEL_ID, AWS_REGION, OPENSEARCH_* if needed.
"""

import json
import os
import re
from typing import Dict, Any, Optional

# strands + Bedrock
from strands import Agent  # type: ignore
from strands.models import BedrockModel  # type: ignore

# Try to import search_tickets tool from your existing agent_service (optional)
try:
    # your existing agent script (the one you showed earlier) exposes `search_tickets`
    from agent_service import search_tickets  # type: ignore

    SEARCH_TOOL_AVAILABLE = True
except Exception:
    search_tickets = None  # type: ignore
    SEARCH_TOOL_AVAILABLE = False

# Configuration via env vars (defaults provided)
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "arn:aws:bedrock:us-east-2:521818209921:inference-profile/us.amazon.nova-lite-v1:0")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
DEFAULT_TOP_K = int(os.environ.get("SUBSTEPS_TOP_K", "5"))

# create Bedrock-backed model for strands
bedrock_model = BedrockModel(
    model_id=BEDROCK_MODEL_ID,
    temperature=0.0,  # deterministic by default; adjust if you want more creativity
    max_tokens=1024,
    region_name=AWS_REGION,
)

# Build system prompt that instructs the LLM to output only JSON
SYSTEM_PROMPT = (
"You are an expert IT support assistant. "
"Input: a single short 'resolution step' such as "
'"Reset password via self-service portal" or "Disabled user account." '
"Task: produce an ordered, actionable list of UI-level substeps to execute that resolution. "
"Each substep should include: id (integer), title (short), step (action text), "
"commands (list of single-line commands or API calls, optional), and notes (optional). "
"IMPORTANT: Do NOT populate or invent the `whereToGo` field here — leave it empty or omit it. "
"We will generate `whereToGo` later using a multimodal LLM that receives a screenshot and the substep. "
"If helpful, you may call the available `search_tickets` tool (if present) to fetch similar historical tickets — do so first. "
"OUTPUT REQUIREMENT: respond with JSON ONLY and nothing else. The JSON must match this schema:\n\n"
"{\n"
' "originalStep": "<the input step>",\n'
' "recommendedSubsteps": [ { "id": 1, "title": "...", "step": "...", "commands": [], "notes": "" }, ... ],\n'
' "sources": [ /* optional tool outputs or short references */ ]\n'
"}\n\n"
"Do not include any commentary, markdown, or extraneous text. If you are uncertain, prefer explicit, testable actions (e.g., where to click, exact menus, exact commands). "
)

# Register tools if available
TOOLS = []
if SEARCH_TOOL_AVAILABLE and search_tickets is not None:
    TOOLS.append(
        search_tickets
    )  # search_tickets should be decorated with @tool in your agent_service

# Create the agent
agent = Agent(
    model=bedrock_model,
    tools=TOOLS,
    system_prompt=SYSTEM_PROMPT,
)


def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Helper: try to find a JSON object in text and parse it.
    Returns dict on success, or None on failure.
    """
    if not text or not isinstance(text, str):
        return None
    # find first { ... } block that looks like JSON
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except Exception:
        # try to be forgiving by cleaning obvious trailing ticks or stray backticks
        cleaned = re.sub(r"`+", "", candidate)
        try:
            return json.loads(cleaned)
        except Exception:
            return None


def suggest_substeps_for_resolution_step(
    resolution_step: str,
    ticket_context: Optional[Dict[str, Any]] = None,
    top_k: int = DEFAULT_TOP_K,
    timeout_seconds: int = 60,
) -> Dict[str, Any]:
    """
    Send a single resolution step + optional ticket context to the strands/Bedrock agent,
    instruct it to produce UI-level substeps, and return the parsed JSON.

    Args:
      resolution_step: e.g. "Reset password via self-service portal."
      ticket_context: optional dict with ticket fields (displayId, subject, requester, priority, site, device_os)
      top_k: how many similar tickets to retrieve (if search_tickets tool is available)
      timeout_seconds: agent call timeout (some Bedrock models may take longer)

    Returns:
      Parsed JSON dict with keys originalStep, recommendedSubsteps, sources
    Raises:
      RuntimeError on failure to parse or other errors.
    """
    if not resolution_step or not isinstance(resolution_step, str):
        raise ValueError("resolution_step must be a non-empty string")

    # Build the instruction. If search_tickets exists, instruct the agent to call it first.
    context_json = json.dumps(ticket_context or {}, default=str)
    if SEARCH_TOOL_AVAILABLE:
        instruction = (
            f"New resolution step: {json.dumps(resolution_step)}\n\n"
            f"Ticket context: {context_json}\n\n"
            f"First, call the `search_tickets` tool with this query (top_k={top_k}) to fetch up to {top_k} similar tickets: "
            f'"{resolution_step}"\n\n'
            "Then synthesize an ordered list of UI-level substeps for the resolution step. "
            "Return JSON matching the system prompt schema, and nothing else."
        )
    else:
        instruction = (
            f"New resolution step: {json.dumps(resolution_step)}\n\n"
            f"Ticket context: {context_json}\n\n"
            "Synthesize an ordered list of UI-level substeps for the resolution step. "
            "Return JSON matching the system prompt schema, and nothing else."
        )

    # Call the agent
    try:
        response = agent(instruction)  # strands Agent will handle tool calls if used
        # Convert response to string and extract JSON
        text = str(response)
        parsed = _extract_json_from_text(text)
        if parsed is None:
            # provide debugging info in the exception
            raise RuntimeError(
                f"Failed to parse JSON from model output. Raw output:\n{text}"
            )
        return parsed
    except Exception as e:
        raise RuntimeError(f"Agent call failed: {e}") from e


# CLI test
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate substeps for a resolution step using strands + Bedrock"
    )
    parser.add_argument("step", help="Resolution step text (wrap in quotes)")
    parser.add_argument("--json", action="store_true", help="print JSON only")
    parser.add_argument(
        "--top_k",
        type=int,
        default=DEFAULT_TOP_K,
        help="how many similar tickets to fetch (if available)",
    )
    args = parser.parse_args()

    try:
        out = suggest_substeps_for_resolution_step(
            args.step, ticket_context=None, top_k=args.top_k
        )
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            print("Original step:", out.get("originalStep"))
            print("\nRecommended Substeps:")
            for s in out.get("recommendedSubsteps", []):
                print(f"{s.get('id')}. {s.get('title')}")
                print(f"   Step: {s.get('step')}")
                if s.get("whereToGo"):
                    print(f"   Where: {s.get('whereToGo')}")
                if s.get("commands"):
                    print(f"   Commands: {s.get('commands')}")
                if s.get("notes"):
                    print(f"   Notes: {s.get('notes')}")
                print()
            if out.get("sources"):
                print("Sources:", out["sources"])
    except Exception as exc:
        print("Error:", exc)
        raise
