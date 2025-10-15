#!/usr/bin/env python3
"""
master_agent.py

Single central Strands agent that orchestrates multiple subagents/tools:
 - agent_substeps_llm.suggest_substeps_for_resolution_step
 - agents.chat_agent.chat_with_agent / search_similar_tickets
 - kb_store.* (local KB helper functions)
 - agents.resolution_steps_agent.search_tickets / suggest_resolution_for_ticket
 - strands_bedrock_agent.analyze_snapshot_for_completion / generate_where_to_go_from_snapshot

The master agent registers each of the above as a Strands @tool so Bedrock AgentCore
can run one single agent that composes the functionality.

Usage:
 - Put this file next to your other modules (agent_substeps_llm.py, agents/chat_agent.py,
   agents/resolution_steps_agent.py, kb_store.py, strands_bedrock_agent.py).
 - Ensure Strands and BedrockModel dependencies are installed and env vars set:
   BEDROCK_MODEL_ID, AWS_REGION, etc.
 - Run: python master_agent.py
"""

import os
import json
import base64
from typing import Any, Dict, Optional, List
from strands import Agent, tool  # type: ignore
from strands.models import BedrockModel  # type: ignore
import agent_substeps_llm as sub_agent_substeps
import chat_agent as sub_chat 
import kb_store as sub_kb
import resolution_steps_agent as sub_resolution
import screen_share_agent as sub_multimodal
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DEFAULT_MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "1024"))
DEFAULT_TEMPERATURE = float(os.environ.get("BEDROCK_TEMPERATURE", "0.0"))

TOOLS = []


@tool(
        name="generate_substeps",
        description="Generate UI-level substeps for a resolution step. Args: (resolution_step: str, ticket_context_json: str, top_k: int). Returns JSON result."
    )
def generate_substeps_tool(resolution_step: str, ticket_context_json: str = "{}", top_k: int = 5) -> Dict[str, Any]:
    try:
        ctx = json.loads(ticket_context_json) if isinstance(ticket_context_json, str) else ticket_context_json
    except Exception:
            ctx = {}
    try:
        result = sub_agent_substeps.suggest_substeps_for_resolution_step(resolution_step, ticket_context=ctx, top_k=top_k)
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": f"generate_substeps error: {e}"}

TOOLS.append(generate_substeps_tool)


@tool(
        name="chat_with_agent",
        description="Conversational helper. Args: (conversation_json:str, question:str, ticket_context_json:str, top_k:int). Returns a dict with answer and optional structured data."
    )
def chat_with_agent_tool(conversation_json: str, question: str, ticket_context_json: str = "{}", top_k: int = 5) -> Dict[str, Any]:
    try:
        conv = json.loads(conversation_json) if isinstance(conversation_json, str) and conversation_json.strip() else []
    except Exception:
        conv = []
    try:
        ctx = json.loads(ticket_context_json) if isinstance(ticket_context_json, str) and ticket_context_json.strip() else {}
    except Exception:
        ctx = {}
    try:
        res = sub_chat.chat_with_agent(conv, question, ticket_context=ctx, top_k=top_k)
        return {"ok": True, "result": res}
    except Exception as e:
        return {"ok": False, "error": f"chat_with_agent error: {e}"}

    # also export a simple search wrapper to get concise ticket lists
if hasattr(sub_chat, "search_similar_tickets"):
    @tool(
            name="search_similar_tickets",
            description="Return concise list of similar tickets. Args: (query_text:str, top_k:int)."
        )
    def search_similar_tickets_tool(query_text: str, top_k: int = 5) -> Dict[str, Any]:
        try:
            res = sub_chat.search_similar_tickets(query_text, top_k=top_k)
            return {"ok": True, "result": res}
        except Exception as e:
            return {"ok": False, "error": f"search_similar_tickets error: {e}"}

    TOOLS.append(search_similar_tickets_tool)

TOOLS.append(chat_with_agent_tool)


@tool(
        name="kb_search",
        description="Search local KB (kb_store). Args: (query_text:str, top_k:int). Returns list of hits."
    )
def kb_search_tool(query_text: str, top_k: int = 5) -> Dict[str, Any]:
    try:
        # prefer high-level function names if present
        if hasattr(sub_kb, "kb_search"):
            hits = sub_kb.kb_search(query_text, top_k=top_k)
        elif hasattr(sub_kb, "search_tickets_by_text"):
            hits = sub_kb.search_tickets_by_text(query_text, top_k=top_k)
        else:
            hits = []
        return {"ok": True, "hits": hits}
    except Exception as e:
        return {"ok": False, "error": f"kb_search error: {e}"}

TOOLS.append(kb_search_tool)


@tool(
        name="search_tickets",
        description="OpenSearch-backed 'search_tickets' tool (if available). Args: (query_text:str, top_k:int). Returns dict with 'results'."
    )
def search_tickets_tool(query_text: str, top_k: int = 3) -> Dict[str, Any]:
    try:
        # resolution_steps_agent.search_tickets is decorated as @tool in that module; it's a normal callable too
        res = sub_resolution.search_tickets(query_text, top_k=top_k)
        return {"ok": True, "result": res}
    except Exception as e:
        return {"ok": False, "error": f"search_tickets error: {e}"}

@tool(
        name="suggest_resolution_for_ticket",
        description="Synthesize resolution steps for a ticket. Args: (ticket_json:str, top_k:int). Returns JSON result."
    )
def suggest_resolution_tool(ticket_json: str, top_k: int = 3) -> Dict[str, Any]:
    try:
        ticket = json.loads(ticket_json) if isinstance(ticket_json, str) else ticket_json
    except Exception:
        ticket = {}
    try:
        res = sub_resolution.suggest_resolution_for_ticket(ticket, top_k=top_k)
        return {"ok": True, "result": res}
    except Exception as e:
        return {"ok": False, "error": f"suggest_resolution error: {e}"}

TOOLS.extend([search_tickets_tool, suggest_resolution_tool])


@tool(
        name="analyze_snapshot",
        description="Analyze base64 image for substep completion. Args: (image_base64:str, substep_text:str, declared_format:str|null). Returns decision/explanation."
    )
def analyze_snapshot_tool(image_base64: str, substep_text: str, declared_format: Optional[str] = None) -> Dict[str, Any]:
    try:
        # Accept either data URL or raw base64
        img_b64 = image_base64
        if image_base64.startswith("data:"):
            try:
                _, payload = image_base64.split(",", 1)
                img_b64 = payload
            except Exception:
                img_b64 = image_base64
        image_bytes = base64.b64decode(img_b64)
    except Exception as e:
        return {"ok": False, "error": f"could not decode image_base64: {e}"}

    try:
        res = sub_multimodal.analyze_snapshot_for_completion(image_bytes, substep_text, declared_format=declared_format)
        return {"ok": True, "result": res}
    except Exception as e:
        return {"ok": False, "error": f"analyze_snapshot error: {e}"}

@tool(
        name="where_to_go",
        description="Extract a short UI path from an image & substep. Args: (image_base64:str, substep_text:str). Returns single-line string."
    )
def where_to_go_tool(image_base64: str, substep_text: str) -> Dict[str, Any]:
    try:
        img_b64 = image_base64
        if image_base64.startswith("data:"):
            try:
                _, payload = image_base64.split(",", 1)
                img_b64 = payload
            except Exception:
                    img_b64 = image_base64
        image_bytes = base64.b64decode(img_b64)
    except Exception as e:
        return {"ok": False, "error": f"could not decode image_base64: {e}"}

    try:
        where = sub_multimodal.generate_where_to_go_from_snapshot(image_bytes, substep_text)
        return {"ok": True, "whereToGo": where}
    except Exception as e:
        return {"ok": False, "error": f"where_to_go error: {e}"}

TOOLS.extend([analyze_snapshot_tool, where_to_go_tool])


master_system_prompt = (
    "You are the Master Orchestrator agent. Your job is to decompose user requests and call specialized tools "
    "when useful. Tools available to you: "
)

available_tools_list = [t.__name__ for t in TOOLS]
if available_tools_list:
    master_system_prompt += ", ".join(available_tools_list) + ". "
else:
    master_system_prompt += "none (no subagent tools available). "

master_system_prompt += (
    "When you need to perform image analysis, call analyze_snapshot or where_to_go. "
    "When you need to fetch similar tickets, call search_tickets or kb_search. "
    "When you need to generate substeps or suggest resolutions, call generate_substeps or suggest_resolution_for_ticket. "
    "When conversing, use chat_with_agent. Always prefer calling a tool for specialized work rather than inventing content. "
    "Return concise, actionable answers. If you cannot complete the request because a tool is unavailable, state which tool is missing."
)

# Create bedrock-backed model (used by the master agent itself)
bedrock_model = BedrockModel(
    model_id=BEDROCK_MODEL_ID,
    temperature=DEFAULT_TEMPERATURE,
    max_tokens=DEFAULT_MAX_TOKENS,
    region_name=AWS_REGION,
)

master_agent = Agent(model=bedrock_model, tools=TOOLS, system_prompt=master_system_prompt)


# Convenience wrapper to call the master agent programmatically
def process_request(user_instruction: str, timeout_seconds: int = 60) -> Dict[str, Any]:
    """
    Ask the master agent to handle `user_instruction`. Returns a dict with keys:
      { ok: bool, result: str | dict, debug?: { raw: str } }
    """
    try:
        response = master_agent(user_instruction)
        text = str(response)
        return {"ok": True, "result": text}
    except Exception as e:
        return {"ok": False, "error": f"master agent call failed: {e}"}

