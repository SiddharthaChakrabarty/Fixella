#!/usr/bin/env python3
"""
suggest_resolution_patch.py

- Sanitizes incoming payloads (removes 'Traceback' pollution).
- Wraps agent calls to handle MaxTokensReachedException gracefully.
- Provides a tuned suggest_resolution_for_ticket function that builds
  concise retrieval context and falls back to a synthesized output when necessary.

Usage:
 - Import `suggest_resolution_for_ticket` into your code and call:
     suggestion = suggest_resolution_for_ticket(new_ticket, agent, search_tickets, top_k=3)
 - If you run this file directly, a mock demo will run.
"""

import json
import re
import logging
from typing import List, Dict, Any, Optional, Callable

# Attempt to import the specific exception used by strands; if unavailable,
# create a local placeholder so code still runs (mock behavior).
try:
    from strands.types.exceptions import MaxTokensReachedException
except Exception:
    class MaxTokensReachedException(Exception):
        """Fallback placeholder for environments without strands installed."""
        pass

logger = logging.getLogger("suggest_resolution_patch")
logging.basicConfig(level=logging.INFO)


# -----------------------
# Sanitizer utilities
# -----------------------
_TRACEBACK_PATTERN = re.compile(r"Traceback\b", flags=re.IGNORECASE)
_FILEPATH_PATTERN = re.compile(r"(?:[A-Za-z]:[\\/]|/)[\w\-\./\\\s:]+(?:\.\w+)?")  # heuristic for paths


def _clean_text_remove_traceback(s: str) -> str:
    """
    Remove the substring 'Traceback' and everything after it, if present.
    Also collapse multiple whitespace and strip punctuation.
    """
    if not isinstance(s, str):
        s = str(s or "")
    m = _TRACEBACK_PATTERN.search(s)
    if m:
        s = s[:m.start()]
    # Remove obvious file paths to avoid leaking stack traces into structured text
    s = _FILEPATH_PATTERN.sub("", s)
    # Collapse whitespace and trim punctuation
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(" \t\n\r\0\x0B.:-")
    return s


def sanitize_sources_in_data(data: Dict[str, Any], fields_to_clean: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Sanitize `resolutionSteps` and optionally other fields inside 'sources' list of a data dict.
    This mutates the dict in-place and also returns it.
    """
    if fields_to_clean is None:
        fields_to_clean = ["resolutionSteps", "notes", "description"]

    sources = data.get("sources") or []
    if not isinstance(sources, list):
        return data

    def clean_steps_list(steps):
        out = []
        for s in steps or []:
            if not isinstance(s, str):
                s = str(s)
            cleaned = _clean_text_remove_traceback(s)
            if cleaned:
                out.append(cleaned)
        return out

    for src in sources:
        for fld in fields_to_clean:
            if fld in src:
                val = src.get(fld)
                if isinstance(val, list):
                    src[fld] = clean_steps_list(val)
                elif isinstance(val, str):
                    cleaned = _clean_text_remove_traceback(val)
                    src[fld] = cleaned
    return data


# -----------------------
# Fallback synthesizer (recreates ordered steps from retrievals)
# -----------------------
def synthesize_steps_from_retrievals(retrievals: List[Dict[str, Any]], max_steps: int = 8) -> List[str]:
    """
    Build an ordered list of resolution steps aggregated from retrievals.
    Prioritizes steps that appear most frequently in the retrievals.
    """
    seen = {}
    order = []
    for r in retrievals:
        for step in (r.get("resolutionSteps") or []):
            normalized = (step or "").strip()
            if not normalized:
                continue
            if normalized not in seen:
                seen[normalized] = 0
                order.append(normalized)
            seen[normalized] += 1
    ordered = sorted(order, key=lambda s: (-seen[s], order.index(s)))
    return ordered[:max_steps]


# -----------------------
# Wrapper for safe agent call
# -----------------------
def safe_agent_call(agent_callable: Callable[[str], Any],
                    instruction: str,
                    retrievals: List[Dict[str, Any]],
                    fallback_synth_fn: Callable[[List[Dict[str, Any]]], List[str]]):
    """
    Call the agent, catch MaxTokensReachedException (or other issues), and return either:
      - agent response (raw) on success, or
      - a fallback dict with synthesized steps on failure.
    """
    try:
        logger.debug("Calling agent with instruction length=%d", len(instruction))
        response = agent_callable(instruction)
        return {"ok": True, "response": response}
    except MaxTokensReachedException as e:
        logger.warning("MaxTokensReachedException encountered: %s", e)
        synthesized = fallback_synth_fn(retrievals)
        return {"ok": False, "reason": "max_tokens", "fallback_synthesized": synthesized}
    except Exception as e:
        logger.exception("Agent call failed with unexpected exception:")
        synthesized = fallback_synth_fn(retrievals)
        return {"ok": False, "reason": "exception", "fallback_synthesized": synthesized, "error": str(e)}


# -----------------------
# Retrieval context builder
# -----------------------
def summarize_for_prompt(hit_src: Dict[str, Any], max_steps: int = 3) -> str:
    subj = hit_src.get("subject") or ""
    steps = hit_src.get("resolutionSteps") or []
    steps_text = " | ".join([s.strip() for s in steps[:max_steps] if s.strip()])
    if steps_text:
        return f"{subj} -> {steps_text}"
    return subj


def build_retrieval_context(retrievals: List[Dict[str, Any]], max_chars: int = 4000) -> str:
    """
    Combine short summaries of retrievals into a single string limited to max_chars.
    This is aggressively truncated to reduce token pressure.
    """
    parts = []
    for r in retrievals:
        summary = summarize_for_prompt(r, max_steps=2)
        if summary:
            parts.append(f"- [{r.get('displayId')}] {summary}")
    combined = "\n".join(parts)
    if len(combined) > max_chars:
        # trim to last complete line within budget
        combined = combined[:max_chars].rsplit("\n", 1)[0]
    return combined


# -----------------------
# Core function: suggest_resolution_for_ticket
# -----------------------
def suggest_resolution_for_ticket(new_ticket: Dict[str, Any],
                                  agent_callable: Callable[[str], Any],
                                  search_tickets_callable: Callable[[str, int], Dict[str, Any]],
                                  top_k: int = 3,
                                  retrieval_summary_max_chars: int = 4000) -> Dict[str, Any]:
    """
    Produce suggestions for a new ticket using retrievals and LLM agent.
    Accepts `agent_callable` (a function that takes a single instruction string and returns agent output)
    and `search_tickets_callable` (a function that takes a query string and top_k int and returns retrievals).
    Returns a dict with keys: recommendedSteps and sources (matching your original structure).
    """
    # Sanitize the new ticket (defensive)
    if "description" in new_ticket and isinstance(new_ticket["description"], str):
        new_ticket["description"] = _clean_text_remove_traceback(new_ticket["description"])

    # Build a compact query to search similar tickets
    query_text = f"{new_ticket.get('subject','')}. Requester: {new_ticket.get('requester',{}).get('name','')}. Subcategory: {new_ticket.get('subcategory','')}. Priority: {new_ticket.get('priority','')}."
    logger.info("Searching tickets with top_k=%d", top_k)
    retrieval_resp = {}
    try:
        retrieval_resp = search_tickets_callable(query_text, top_k=top_k) or {}
    except Exception as e:
        logger.exception("search_tickets_callable failed; continuing with empty retrievals: %s", e)
        retrieval_resp = {}

    retrievals = retrieval_resp.get("results", []) if retrieval_resp else []
    # Sanitize retrievals sources in case they contain tracebacks (defensive)
    for r in retrievals:
        sanitize_sources_in_data({"sources": [r]})

    # Build retrieval summary with strict char limit
    retrieval_summary = build_retrieval_context(retrievals, max_chars=retrieval_summary_max_chars) or "(no similar tickets found)"

    # Compose instruction (keep system prompt short here; long system prompt should be in agent initialization)
    instruction_obj = {
        "task": "Generate concise ordered resolution steps for the new ticket. For each step include: step, supportingDisplayIds, notes",
        "new_ticket": {
            "displayId": new_ticket.get("displayId"),
            "subject": new_ticket.get("subject"),
            "requester": new_ticket.get("requester"),
            "subcategory": new_ticket.get("subcategory"),
            "priority": new_ticket.get("priority"),
            "description": new_ticket.get("description")
        },
        "context_retrievals_summary": retrieval_summary,
        "notes": "Return valid JSON with keys recommendedSteps (ordered) and sources (the retrieved ticket objects). Be concise."
    }

    instruction_text = json.dumps(instruction_obj, indent=0)

    # Call agent safely
    safe_call = safe_agent_call(agent_callable, instruction_text, retrievals, synthesize_steps_from_retrievals)

    if safe_call.get("ok"):
        raw_response = safe_call["response"]
        # Try to extract and parse JSON from agent response (robust)
        out_text = str(raw_response)
        parsed = None
        try:
            start = out_text.find("{")
            end = out_text.rfind("}") + 1
            if start != -1 and end != -1 and end > start:
                candidate = out_text[start:end]
                parsed = json.loads(candidate)
        except Exception:
            parsed = None

        if parsed is None:
            # If agent returned something non-JSON, fall back to synthesized steps
            synthesized = synthesize_steps_from_retrievals(retrievals)
            recommended = []
            for s in synthesized:
                supporting = [r["displayId"] for r in retrievals if s in (r.get("resolutionSteps") or [])]
                recommended.append({
                    "step": s,
                    "supportingDisplayIds": supporting,
                    "notes": ""
                })
            parsed = {
                "recommendedSteps": recommended,
                "sources": retrievals
            }
        # Final sanitation on parsed structure (ensure no tracebacks)
        sanitize_sources_in_data(parsed)
        return parsed

    else:
        # fallback path if agent failed due to tokens or error
        synthesized = safe_call.get("fallback_synthesized", [])
        recommended = []
        for s in synthesized:
            supporting = [r["displayId"] for r in retrievals if s in (r.get("resolutionSteps") or [])]
            recommended.append({
                "step": s,
                "supportingDisplayIds": supporting,
                "notes": ""
            })
        out = {
            "recommendedSteps": recommended,
            "sources": retrievals,
            "fallback": True,
            "fallback_reason": safe_call.get("reason"),
        }
        # sanitize just in case
        sanitize_sources_in_data(out)
        return out


# -----------------------
# Demo / Mocking (for local testing)
# -----------------------
if __name__ == "__main__":
    # Simple mock search_tickets that returns the sample retrievals from your earlier message
    def mock_search_tickets(query_text: str, top_k: int = 3) -> Dict[str, Any]:
        sample_sources = [
            {"displayId": "3", "subject": "Mouse issues",
             "resolutionSteps": ["Checked connections or batteries.", "Cleaned mouse sensor.", "Updated mouse drivers.", "Tested with another mouse.", "Adjusted mouse settings.", "Issue resolved by cleaning."]},
            {"displayId": "125", "subject": "Mouse issues",
             "resolutionSteps": ["Checked connections or batteries.", "Cleaned mouse sensor.", "Updated mouse drivers.", "Tested with another mouse.", "Adjusted mouse settings.", "Issue resolved by cleaning."]},
            {"displayId": "112", "subject": "Mouse issues",
             "resolutionSteps": ["Checked connections or batteries.", "Cleaned mouse sensor.", "Updated mouse drivers.", "Tested with another mouse.", "Adjusted mouse settings.", "Issue resolved by cleaning."]},
            {"displayId": "103", "subject": "Mouse issues",
             "resolutionSteps": ["Checked connections or batteries.", "Cleaned mouse sensorTraceback (most recent call last): ...", "Updated mouse drivers.", "Tested with another mouse.", "Adjusted mouse settings.", "Issue resolved by cleaning."]}
        ]
        # return top_k items
        return {"results": sample_sources[:max(1, min(top_k, len(sample_sources)))]}

    # Mock agent that intentionally raises MaxTokensReachedException if instruction is long
    class MockAgent:
        def __init__(self, max_len_allowed=800):
            self.max_len_allowed = max_len_allowed

        def __call__(self, instruction_text):
            if len(instruction_text) > self.max_len_allowed:
                raise MaxTokensReachedException("mock max tokens reached for demo")
            # else return a JSON string (simulating a good agent response)
            response = {
                "recommendedSteps": [
                    {"step": "Cleaned mouse sensor.", "supportingDisplayIds": ["3", "125"], "notes": "Use a microfiber cloth."},
                    {"step": "Checked connections or batteries.", "supportingDisplayIds": ["112", "103"], "notes": "Verify cable and battery level."}
                ],
                "sources": [
                    {"displayId": "3", "subject": "Mouse issues", "resolutionSteps": ["Cleaned mouse sensor.", "Issue resolved by cleaning."]}
                ]
            }
            return json.dumps(response)

    demo_agent = MockAgent(max_len_allowed=600)

    # Example new ticket
    new_ticket_example = {
        "displayId": "NEW-001",
        "subject": "Mouse issues",
        "requester": {"name": "Jim Halpert"},
        "subcategory": "Access",
        "priority": "High",
        "description": "User reports that left mouse button is not working. Traceback: some long stack..."
    }

    # Run demo (this will exercise the fallback because the mock agent's threshold is short)
    suggestion = suggest_resolution_for_ticket(new_ticket_example, demo_agent, mock_search_tickets, top_k=4)
    print(json.dumps(suggestion, indent=2, default=str))
