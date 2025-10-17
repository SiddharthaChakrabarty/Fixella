# mcp_server.py
from mcp.server.fastmcp import FastMCP
import json
import base64

# import your modules (ensure package layout supports this)
import master_agent            # your master agent that already composed tools
# or import the underlying modules so you can call them directly:
import agent_substeps_llm as sub_agent_substeps
import chat_agent as sub_chat
import kb_store as sub_kb
import resolution_steps_agent as sub_resolution
import screen_share_agent as sub_multimodal

mcp = FastMCP(host="0.0.0.0", stateless_http=True)

# Tool wrappers: the decorator exposes the function to agents via MCP.
# Keep wrapper signatures simple: JSON strings or base64 where appropriate.

@mcp.tool()
def generate_substeps(resolution_step: str, ticket_context_json: str = "{}", top_k: int = 5):
    try:
        return sub_agent_substeps.suggest_substeps_for_resolution_step(
            resolution_step,
            ticket_context=json.loads(ticket_context_json or "{}"),
            top_k=int(top_k),
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcp.tool()
def chat_with_agent(conversation_json: str, question: str, ticket_context_json: str = "{}", top_k: int = 5):
    try:
        conv = json.loads(conversation_json or "[]")
        ctx = json.loads(ticket_context_json or "{}")
        return sub_chat.chat_with_agent(conv, question, ticket_context=ctx, top_k=int(top_k))
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcp.tool()
def search_similar_tickets(query_text: str, top_k: int = 5):
    try:
        return sub_chat.search_similar_tickets(query_text, top_k=int(top_k))
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcp.tool()
def kb_search(query_text: str, top_k: int = 5):
    try:
        if hasattr(sub_kb, "kb_search"):
            hits = sub_kb.kb_search(query_text, top_k=top_k)
        else:
            hits = sub_kb.search_tickets_by_text(query_text, top_k=top_k)
        return {"ok": True, "hits": hits}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcp.tool()
def search_tickets(query_text: str, top_k: int = 3):
    try:
        return sub_resolution.search_tickets(query_text, top_k=int(top_k))
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcp.tool()
def suggest_resolution_for_ticket(ticket_json: str, top_k: int = 3):
    try:
        return sub_resolution.suggest_resolution_for_ticket(json.loads(ticket_json), top_k=int(top_k))
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcp.tool()
def analyze_snapshot(image_base64: str, substep_text: str, declared_format: str = None):
    try:
        b = base64.b64decode(image_base64) if not image_base64.startswith("data:") else base64.b64decode(image_base64.split(",",1)[1])
        return sub_multimodal.analyze_snapshot_for_completion(b, substep_text, declared_format=declared_format)
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcp.tool()
def where_to_go(image_base64: str, substep_text: str):
    try:
        b = base64.b64decode(image_base64) if not image_base64.startswith("data:") else base64.b64decode(image_base64.split(",",1)[1])
        return sub_multimodal.generate_where_to_go_from_snapshot(b, substep_text)
    except Exception as e:
        return {"ok": False, "error": str(e)}

if __name__ == "__main__":
    # FastMCP default streamable-http listens on 0.0.0.0:8000 and exposes /mcp
    mcp.run(transport="streamable-http")
