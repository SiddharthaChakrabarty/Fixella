# backend_server.py
import os
import json
import base64
import re
from datetime import datetime

from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO, emit

import boto3
from botocore.exceptions import ClientError

# Optional strands integration (if you want to run an Agent rather than direct invoke).
# If you have `strands-agents` installed and want the more agentic flow, uncomment and
# follow the small example near the bottom of the file.
# from strands import Agent, tool
# from strands.models import BedrockModel

# Add these imports at top for image detection/IO
import imghdr
import io

# --- App setup ---
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Paths & env ---
SNAPSHOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "snapshots"))
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")
# Choose a multimodal-capable model you've been granted access to (example shown).
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "256"))
TEMPERATURE = float(os.environ.get("BEDROCK_TEMPERATURE", "0.0"))

# boto3 bedrock runtime client (used for InvokeModel multimodal)
bedrock_client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)




def _detect_image_format_from_bytes(image_bytes: bytes, fallback_mime: str = None) -> str:
    """
    Return a short format string suitable for Bedrock's 'format' (e.g. 'png', 'jpeg', 'webp').
    Uses imghdr to inspect bytes first; falls back to MIME string like 'image/jpeg'.
    """
    detected = imghdr.what(None, h=image_bytes)  # returns 'png', 'jpeg', 'gif', etc. or None
    if detected:
        return detected
    if fallback_mime:
        try:
            return fallback_mime.split("/", 1)[1]
        except Exception:
            pass
    return "png"


def _safe_extract_text(model_response):
    """
    Prefer the canonical path used in Bedrock multimodal examples:
      model_response["output"]["message"]["content"][0]["text"]
    Fallback: walk the JSON and collect strings.
    """
    try:
        return model_response["output"]["message"]["content"][0]["text"]
    except Exception:
        texts = []

        def walk(x):
            if isinstance(x, dict):
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for i in x:
                    walk(i)
            elif isinstance(x, str):
                texts.append(x)

        walk(model_response)
        if texts:
            return "\n".join(t.strip() for t in texts if t.strip())
        return json.dumps(model_response)[:4000]


def analyze_snapshot_for_completion(
    image_bytes: bytes,
    substep_text: str,
    declared_format: str = None,
    force_png: bool = False
):
    """
    Robust Bedrock multimodal call that determines whether a substep
    has been visually completed in the given image.
    """

    detected_format = _detect_image_format_from_bytes(image_bytes, fallback_mime=declared_format)
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    system_list = [
        {
            "text": (
                "You are a highly consistent visual verification assistant. "
                "Your task is to look carefully at an image and decide if a given substep "
                "has been COMPLETED. "
                "You must respond with EXACTLY TWO LINES:\n"
                "Line 1: either 'YES' or 'NO' (in uppercase, with no punctuation or other words)\n"
                "Line 2: a short factual explanation (under 20 words) describing visual evidence only.\n\n"
                "Rules:\n"
                "- Never guess or assume intent.\n"
                "- Only use visible evidence from the image.\n"
                "- If uncertain, respond 'NO'.\n"
                "- Do NOT include extra text, markdown, or commentary.\n"
                "- The first word in the entire output must be strictly 'YES' or 'NO'.\n"
            )
        }
    ]

    message_list = [
        {
            "role": "user",
            "content": [
                {
                    "image": {
                        "format": detected_format,
                        "source": {"bytes": b64},
                    }
                },
                {
                    "text": (
                        f"Visual verification target:\n{substep_text.strip()}\n\n"
                        "Question: Based on the actual visual evidence, has this substep been completed?\n\n"
                        "Remember: respond only as per the format described. "
                        "Do not justify beyond a single evidence sentence."
                    )
                },
            ],
        }
    ]

    native_request = {
        "schemaVersion": "messages-v1",
        "system": system_list,
        "messages": message_list,
        "inferenceConfig": {
            "maxTokens": MAX_TOKENS,
            "temperature": 0.0,         # force determinism
            "topP": 0.1,               # optional reproducibility
        },
    }

    def _invoke_once():
        response = bedrock_client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(native_request),
        )
        raw = response["body"].read()
        return json.loads(raw)

    model_response = _invoke_once()
    text = _safe_extract_text(model_response) or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    decision, explanation = None, ""

    if lines:
        first = lines[0].split()[0].upper() if lines[0] else ""
        if first == "YES":
            decision = "YES"
        elif first == "NO":
            decision = "NO"

        if len(lines) > 1:
            explanation = lines[1]
        elif len(lines) == 1:
            explanation = ""

    # fallback: retry once if unclear
    if decision not in ("YES", "NO"):
        model_response = _invoke_once()
        text = _safe_extract_text(model_response) or ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        first = lines[0].split()[0].upper() if lines else ""
        if first == "YES":
            decision = "YES"
        elif first == "NO":
            decision = "NO"
        if len(lines) > 1:
            explanation = lines[1]

    if decision not in ("YES", "NO"):
        decision = "NO"
        explanation = explanation or "Unclear or ambiguous output from model."

    return {
        "decision": decision,
        "explanation": explanation,
        "raw": model_response,
    }

def generate_where_to_go_from_snapshot(image_bytes: bytes, substep_text: str, declared_format: str = None) -> str:
    detected_format = _detect_image_format_from_bytes(image_bytes, fallback_mime=declared_format)
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    system_list = [
        {
            "text": (
                        "You are a concise UI path extraction assistant. "
        "Given a screenshot (image) showing the current UI and a short substep description, "
        "output a single short `whereToGo` string describing **where** in the UI to perform the action. "
        "Examples: 'Windows: Start > Settings > Accounts', 'Gmail: Settings (gear) > See all settings > Accounts', "
        "or 'Admin Console → Users → Search user'.\n\n"
        "RESPONSE RULES: Return EXACTLY one plain text line (no JSON, no quotes, no punctuation lines). "
        "Keep it short (under 20 words). If unsure, prefer a conservative UI path or respond with 'Unknown'."
        )
        }
        ]
    
    message_list = [
        {
            "role": "user",
            "content": [
            {
                "image": {
                "format": detected_format,
                "source": {"bytes": b64},
                }
            },
        {
        "text": (
        f"Substep: {substep_text.strip()}\n\n"
        "Question: Based on the image, provide a short 'whereToGo' UI path for this substep.\n"
        )
        },
        ],
        }
        ]

    native_request = {
        "schemaVersion": "messages-v1",
        "system": system_list,
        "messages": message_list,
        "inferenceConfig": {
        "maxTokens": 60,
        "temperature": 0.0,
        "topP": 0.1,
        },
    }

    try:
        response = bedrock_client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(native_request),
        )
        raw = response["body"].read()
        model_response = json.loads(raw)
        text = _safe_extract_text(model_response) or ""
        # take first non-empty line
        for ln in text.splitlines():
            ln = ln.strip()
            if ln:
            # sanitize common prefixes like 'Where:'
                ln = re.sub(r"^Where:\s*", "", ln, flags=re.IGNORECASE)
                return ln
            return "Unknown"
    except Exception as e:
        print("generate_where_to_go_from_snapshot error:", e)
        return "Unknown"


@socketio.on("snapshot")
def handle_snapshot(data):
    """
    Expects data:
      { image: "data:image/png;base64,....", ticket_suggestion: "...", active_id: <substep id> }
    Behavior:
      - Save the image
      - Call Bedrock to ask YES/NO whether the substep is done (using analyze_snapshot_for_completion)
      - Emit back "snapshot_ack" with decision
    """
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
    ext = _detect_image_format_from_bytes(image_bytes, fallback_mime=mime) or "png"
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
            where_text = generate_where_to_go_from_snapshot(image_bytes,
            substep_text, declared_format=mime)
            emit("where_response", {"substep_id": active_id, "whereToGo":
            where_text, "filepath": filename, "timestamp": datetime.utcnow().isoformat()
            + "Z"})
        except Exception as e:
            print("Error generating whereToGo:", e)
            # still continue; we won't fail the whole snapshot flow

    # Analyze with Bedrock
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
        print("Error analyzing snapshot with Bedrock:", e)
        emit("snapshot_ack", {
            "substep_id": active_id,
            "decision": "NO",
            "explanation": f"Server error during analysis: {e}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })


@app.route("/")
def index():
    return "WebSocket server running."


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1") not in ("0", "false", "no")
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5001"))
    socketio.run(app, debug=debug, host=host, port=port)
