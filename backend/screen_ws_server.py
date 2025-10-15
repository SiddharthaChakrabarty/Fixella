# backend_server.py  (modified to use master_agent where available)
import os
import json
import base64
import re
from datetime import datetime

from flask import Flask
from flask_cors import CORS    #type: ignore
from flask_socketio import SocketIO, emit

# Add these imports at top for image detection/IO
import imghdr
import io

# try to import master agent tools first (preferred)
MASTER_AVAILABLE = False
analyze_snapshot_tool = None
where_to_go_tool = None
try:
    import master_agent as master_agent_module  # type: ignore
    MASTER_AVAILABLE = True
    analyze_snapshot_tool = getattr(master_agent_module, "analyze_snapshot_tool", None)
    where_to_go_tool = getattr(master_agent_module, "where_to_go_tool", None)
except Exception:
    MASTER_AVAILABLE = False

# fallback: old subagent if available
try:
    from agents.screen_share_agent import (
        analyze_snapshot_for_completion as fallback_analyze_snapshot,
        generate_where_to_go_from_snapshot as fallback_generate_where_to_go,
    )
    FALLBACK_SCREEN_SHARE_AVAILABLE = True
except Exception:
    fallback_analyze_snapshot = None
    fallback_generate_where_to_go = None
    FALLBACK_SCREEN_SHARE_AVAILABLE = False

# --- App setup ---
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Paths & env ---
SNAPSHOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "snapshots"))
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

@socketio.on("snapshot")
def handle_snapshot(data):
    img_data = data.get("image", "")
    substep_text = data.get("ticket_suggestion", "") or ""
    active_id = data.get("active_id", None)
    request_where = bool(data.get("request_where", False))

    if not isinstance(img_data, str) or not img_data.startswith("data:image"):
        emit("snapshot_ack", {
            "substep_id": active_id,
            "decision": "NO",
            "explanation": "Invalid image data (expected data URL).",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
        return

    try:
        header, b64data = img_data.split(",", 1)
        mime = None
        if header.startswith("data:"):
            parts = header[5:].split(";")
            if parts:
                mime = parts[0]
    except Exception:
        emit("snapshot_ack", {"substep_id": active_id, "decision": "NO", "explanation": "Malformed image data.", "timestamp": datetime.utcnow().isoformat() + "Z"})
        return

    try:
        image_bytes = base64.b64decode(b64data)
    except Exception as e:
        emit("snapshot_ack", {"substep_id": active_id, "decision": "NO", "explanation": f"Could not decode image: {e}", "timestamp": datetime.utcnow().isoformat() + "Z"})
        return

    # save snapshot to disk (audit)
    now = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    ext = imghdr.what(None, h=image_bytes) or "png"
    filename = f"snapshot_{now}.{ext}"
    filepath = os.path.join(SNAPSHOT_DIR, filename)
    try:
        with open(filepath, "wb") as f:
            f.write(image_bytes)
    except Exception as e:
        print(f"Warning: failed to persist snapshot to disk: {e}")

    # If requested, generate whereToGo and emit it back immediately
    if request_where and active_id is not None:
        # prefer master_agent where_to_go_tool if available
        if MASTER_AVAILABLE and where_to_go_tool is not None:
            try:
                # pass data URL so tool can decode; it accepts either data URL or raw base64
                tool_res = where_to_go_tool(img_data, substep_text)
                if tool_res.get("ok"):
                    where_text = tool_res.get("whereToGo")
                else:
                    where_text = "Unknown"
                emit("where_response", {"substep_id": active_id, "whereToGo": where_text, "filepath": filename, "timestamp": datetime.utcnow().isoformat() + "Z"})
            except Exception as e:
                print("Error generating whereToGo via master_agent:", e)
                # fallback to existing function if available
                if FALLBACK_SCREEN_SHARE_AVAILABLE:
                    try:
                        where_text = fallback_generate_where_to_go(image_bytes, substep_text, declared_format=mime)
                        emit("where_response", {"substep_id": active_id, "whereToGo": where_text, "filepath": filename, "timestamp": datetime.utcnow().isoformat() + "Z"})
                    except Exception as ex:
                        print("Fallback whereToGo also failed:", ex)
                else:
                    emit("where_response", {"substep_id": active_id, "whereToGo": "Unknown", "filepath": filename, "timestamp": datetime.utcnow().isoformat() + "Z"})
        elif FALLBACK_SCREEN_SHARE_AVAILABLE:
            try:
                where_text = fallback_generate_where_to_go(image_bytes, substep_text, declared_format=mime)
                emit("where_response", {"substep_id": active_id, "whereToGo": where_text, "filepath": filename, "timestamp": datetime.utcnow().isoformat() + "Z"})
            except Exception as e:
                print("Fallback whereToGo failed:", e)
                emit("where_response", {"substep_id": active_id, "whereToGo": "Unknown", "filepath": filename, "timestamp": datetime.utcnow().isoformat() + "Z"})
        else:
            emit("where_response", {"substep_id": active_id, "whereToGo": "Unknown", "filepath": filename, "timestamp": datetime.utcnow().isoformat() + "Z"})

    # Analyze with master agent or fallback
    try:
        if MASTER_AVAILABLE and analyze_snapshot_tool is not None:
            try:
                tool_res = analyze_snapshot_tool(img_data, substep_text, declared_format=mime)
                if tool_res.get("ok"):
                    res = tool_res.get("result", {})
                    decision = res.get("decision", "NO")
                    explanation = res.get("explanation", "")
                else:
                    decision = "NO"
                    explanation = tool_res.get("error", "tool error")
            except Exception as e:
                print("Error analyzing snapshot via master_agent:", e)
                # fallback to original
                if FALLBACK_SCREEN_SHARE_AVAILABLE:
                    fb = fallback_analyze_snapshot(image_bytes, substep_text, declared_format=mime)
                    decision = fb.get("decision", "NO")
                    explanation = fb.get("explanation", "")
                else:
                    decision = "NO"
                    explanation = f"Analysis failed: {e}"
        elif FALLBACK_SCREEN_SHARE_AVAILABLE:
            fb = fallback_analyze_snapshot(image_bytes, substep_text, declared_format=mime)
            decision = fb.get("decision", "NO")
            explanation = fb.get("explanation", "")
        else:
            decision = "NO"
            explanation = "No analysis agent available."
        emit_payload = {
            "substep_id": active_id,
            "decision": decision,
            "explanation": explanation,
            "filepath": filename,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        emit("snapshot_ack", emit_payload)
        print("snapshot ack emitted:", emit_payload)
    except Exception as e:
        print("Error analyzing snapshot with agent:", e)
        emit("snapshot_ack", {
            "substep_id": active_id,
            "decision": "NO",
            "explanation": f"Server error during analysis: {e}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

@app.route("/")
def index():
    return "WebSocket server running (using master_agent when available)."

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1") not in ("0", "false", "no")
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5001"))
    socketio.run(app, debug=debug, host=host, port=port)
