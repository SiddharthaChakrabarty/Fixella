# backend_server.py
import os
import json
import base64
from datetime import datetime

from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO, emit

import boto3
from botocore.exceptions import ClientError

# --- App setup ---
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Paths & env ---
SNAPSHOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "snapshots"))
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "512"))
TEMPERATURE = float(os.environ.get("BEDROCK_TEMPERATURE", "0.0"))

# boto3 bedrock client
bedrock_client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)


def _safe_extract_text(model_response):
    """
    Prefer the canonical path used in Bedrock multimodal examples:
      model_response["output"]["message"]["content"][0]["text"]
    Fallback: walk the JSON and collect strings.
    """
    try:
        return model_response["output"]["message"]["content"][0]["text"]
    except Exception:
        # walk and accumulate strings
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


def analyze_snapshot_with_nova(image_bytes: bytes, ticket_suggestion: str):
    """
    Create a messages-v1 multimodal invoke_model payload that matches
    AWS Nova/Bedrock docs for image+text prompts.
    Uses inferenceConfig (camelCase) to avoid ValidationException.
    """
    # Base64 encode the image for the InvokeModel JSON body (Invoke expects base64 for images)
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Build messages array per Bedrock docs (messages-v1)
    system_list = [
        {
            "text": (
                "You are an IT support assistant. Given a screenshot, provide "
                "precise, concise instructions on where to click or which menu to use."
            )
        }
    ]

    # The user message content includes the image and the instruction text
    message_list = [
        {
            "role": "user",
            "content": [
                {
                    # Image content format taken from AWS docs: format + source.bytes (base64 string)
                    "image": {
                        "format": "png",
                        "source": {
                            # For InvokeModel (non-Converse): pass base64-encoded string here
                            "bytes": b64
                        },
                    }
                },
                {
                    "text": (
                        f"Ticket suggestion: {ticket_suggestion}\n\n"
                        "Analyze the screenshot and tell the user exactly where to go or click. "
                        "Be concise and specific: use menu names, button labels, and approximate location (e.g., top-right)."
                    )
                },
            ],
        }
    ]

    native_request = {
        # messages-v1 schema per Bedrock docs for multimodal models (Nova, etc.)
        "schemaVersion": "messages-v1",
        "system": system_list,
        "messages": message_list,
        # Use inferenceConfig with camelCase fields (maxTokens, temperature) — NOT max_tokens
        "inferenceConfig": {"maxTokens": MAX_TOKENS, "temperature": TEMPERATURE},
    }

    try:
        response = bedrock_client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            # boto3 will accept either a str or bytes; docs show json.dumps(...)
            body=json.dumps(native_request),
        )
    except ClientError as e:
        # bubble up with helpful message
        raise RuntimeError(f"Bedrock invoke_model failed: {e}") from e

    # parse the response body
    try:
        raw = response["body"].read()
        model_response = json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"Failed to parse Bedrock response: {e}\nRaw: {raw[:2000]}") from e

    # Extract text using canonical path or fallback
    suggestion = _safe_extract_text(model_response)
    return suggestion


@socketio.on("snapshot")
def handle_snapshot(data):
    """
    Expects data:
      { image: "data:image/png;base64,....", ticket_suggestion: "..." }
    """
    img_data = data.get("image", "")
    ticket_suggestion = data.get("ticket_suggestion", "No suggestion provided.")

    if not isinstance(img_data, str) or not img_data.startswith("data:image"):
        emit("nova_suggestion", {"suggestion": "Invalid image data (expected data URL)."})
        return

    try:
        header, b64data = img_data.split(",", 1)
    except Exception:
        emit("nova_suggestion", {"suggestion": "Malformed image data."})
        return

    # decode
    try:
        image_bytes = base64.b64decode(b64data)
    except Exception as e:
        emit("nova_suggestion", {"suggestion": f"Could not decode image: {e}"})
        return

    # save to snapshots dir for audit/debug
    now = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"snapshot_{now}.png"
    filepath = os.path.join(SNAPSHOT_DIR, filename)
    try:
        with open(filepath, "wb") as f:
            f.write(image_bytes)
    except Exception as e:
        print(f"Warning: failed to persist snapshot to disk: {e}")

    print(f"Saved snapshot: {filepath}")

    # Analyze with Bedrock
    try:
        suggestion = analyze_snapshot_with_nova(image_bytes, ticket_suggestion)
        print("Bedrock suggestion:\n", suggestion)
        emit("nova_suggestion", {"suggestion": suggestion})
    except Exception as e:
        print("Error analyzing snapshot with Bedrock:", e)
        emit("nova_suggestion", {"suggestion": f"Error analyzing snapshot: {e}"})


@app.route("/")
def index():
    return "WebSocket server running."


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1") not in ("0", "false", "no")
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    # keep the same port you used previously
    port = int(os.getenv("FLASK_PORT", "5001"))
    socketio.run(app, debug=debug, host=host, port=port)
