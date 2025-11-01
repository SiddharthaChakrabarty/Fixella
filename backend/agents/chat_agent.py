#!/usr/bin/env python3
"""
agents/chat_agent.py

Bedrock/strands-backed conversational helper.

Changes:
 - For "similar tickets" queries we return only the concise list of hits (no AI summary).
 - Conversational replies remain handled by the agent; system prompt asks for concise responses.
"""

import os
import re
import json
from typing import Any, Dict, List, Optional
from strands import Agent  # type: ignore
from strands.models import BedrockModel  # type: ignore
from agents.resolution_steps_agent import search_tickets

BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "arn:aws:bedrock:us-east-2:521818209921:inference-profile/us.amazon.nova-lite-v1:0")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
DEFAULT_TOP_K = int(os.environ.get("CHAT_TOP_K", "5"))

bedrock_model = None
agent = None


bedrock_model = BedrockModel(
            model_id=BEDROCK_MODEL_ID,
            temperature=0.2,
            max_tokens=1024,
            region_name=AWS_REGION,
)

SYSTEM_PROMPT = (
            "You are Fixella AI, an expert IT support assistant. Answer concisely and directly. "
            "When asked for similar tickets, return only the matching tickets (no extra commentary). "
            "When answering conversational questions, be brief and actionable."
)

# register search tool with agent if available (agent may call it when needed)
tools = [search_tickets]
agent = Agent(model=bedrock_model, tools=tools, system_prompt=SYSTEM_PROMPT)



def _looks_like_search_request(question: str) -> Optional[str]:
    if not question:
        return None
    q = question.strip().lower()
    patterns = [
        r"similar (tickets|issues) (to|for)\s+(.+)$",
        r"tickets (like|about)\s+(.+)$",
        r"any (tickets|issues) (about|for)\s+(.+)$",
        r"show (similar )?(tickets|issues) (for|to)\s+(.+)$",
        r"similar tickets\s*[:\-]\s*(.+)$",
    ]
    for p in patterns:
        m = re.search(p, q)
        if m:
            groups = [g for g in m.groups() if g]
            target = groups[-1]
            return target.strip(" \"'?.!")
    return None


def _format_search_hits_text(hits: List[Dict[str, Any]], top_k: int = 5) -> str:
    """Return a concise, plain-text numbered list of hits (top_k)."""
    if not hits:
        return "No similar tickets found."
    lines = []
    for i, h in enumerate(hits[:top_k], start=1):
        display = h.get("displayId") or h.get("ticketId") or f"ticket-{i}"
        subject = h.get("subject", "No subject")
        lines.append(f"{i}. {display}: {subject}")
    return "\n".join(lines)


def search_similar_tickets(query_text: str, top_k: int = DEFAULT_TOP_K) -> Dict[str, Any]:
    """
    Call the search_tickets function and return structured hits.
    Returns: { ok: bool, hits: [...], error: Optional[str] }
    """
    try:
        raw = search_tickets(query_text, top_k=top_k)
        if isinstance(raw, dict) and "results" in raw:
            hits = raw["results"]
        elif isinstance(raw, list):
            hits = raw
        else:
            hits = raw or []
        return {"ok": True, "hits": hits, "error": None}
    except Exception as e:
        return {"ok": False, "hits": [], "error": f"search_tickets failed: {e}"}


def chat_with_agent(
    conversation: Optional[List[Dict[str, str]]],
    question: str,
    ticket_context: Optional[Dict[str, Any]] = None,
    top_k: int = DEFAULT_TOP_K,
) -> Dict[str, Any]:
    """
    Returns a concise response object:
      { answer: str, sources?: [...], search_hits?: [...], structured?: {...}, error?: str }
    For 'similar tickets' queries we return only the ticket list (no extra AI summary).
    """
    if not question:
        return {"answer": "", "error": "Empty question"}

    # Detect explicit "similar tickets" intent
    search_target = _looks_like_search_request(question)
    if search_target:
        search_res = search_similar_tickets(search_target, top_k=top_k)
        if search_res["ok"]:
            hits = search_res["hits"]
            # concise plain list only
            answer_text = _format_search_hits_text(hits, top_k=top_k)
            return {
                "answer": answer_text,
                "sources": [
                    {"displayId": h.get("displayId"), "subject": h.get("subject"), "ticketId": h.get("ticketId")}
                    for h in hits
                ],
                "search_hits": hits,
            }
        # if search failed, fall through to agent fallback

    # Build compact transcript and ask agent to respond concisely
    transcript_lines = []
    for m in (conversation or []):
        sender = m.get("sender", "user").upper()
        text = m.get("text", "")
        transcript_lines.append(f"{sender}: {text}")
    transcript_lines.append(f"USER: {question}")
    transcript = "\n".join(transcript_lines)
    ctx = json.dumps(ticket_context or {}, default=str)

    instruction = (
        f"Conversation:\n{transcript}\n\n"
        f"Ticket context: {ctx}\n\n"
        "Respond briefly and directly. Do not add long explanations."
    )

    try:
        resp = agent(instruction)
        resp_text = str(resp).strip()
        # try to extract structured JSON if model produced it
        parsed = None
        try:
            start = resp_text.find("{")
            end = resp_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                parsed = json.loads(resp_text[start:end+1])
        except Exception:
            parsed = None

        result = {"answer": resp_text}
        if parsed:
            result["structured"] = parsed
        return result
    except Exception as e:
        return {"answer": "", "error": f"Agent call failed: {e}"}
