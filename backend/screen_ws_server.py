# ### FILE: backend_server.py
# NOTE: This is the modified backend_server.py that imports the above module and uses
# its functions. It closely follows the structure of your original file but removes
# direct bedrock runtime usage and instead calls the strands agent wrapper.

# (Place this file next to strands_bedrock_agent.py and run as before.)

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

# import the new strands-based agent functions
from agents.screen_share_agent import (
    analyze_snapshot_for_completion,
    generate_where_to_go_from_snapshot,
)

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
        try:
            where_text = generate_where_to_go_from_snapshot(image_bytes, substep_text, declared_format=mime)
            emit("where_response", {"substep_id": active_id, "whereToGo": where_text, "filepath": filename, "timestamp": datetime.utcnow().isoformat() + "Z"})
        except Exception as e:
            print("Error generating whereToGo:", e)

    # Analyze with strands-based agent
    try:
        result = analyze_snapshot_for_completion(image_bytes, substep_text, declared_format=mime)
        decision = result.get("decision", "NO")
        explanation = result.get("explanation", "")
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
    return "WebSocket server running (using strands agent)."


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1") not in ("0", "false", "no")
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5001"))
    socketio.run(app, debug=debug, host=host, port=port)
