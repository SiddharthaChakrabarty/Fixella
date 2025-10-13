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

# Add these imports at top
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
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "512"))
TEMPERATURE = float(os.environ.get("BEDROCK_TEMPERATURE", "0.0"))

# boto3 bedrock client
bedrock_client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)


def _detect_image_format_from_bytes(image_bytes: bytes, fallback_mime: str = None) -> str:
    """
    Return a short format string suitable for Bedrock's 'format' (e.g. 'png', 'jpeg', 'webp').
    Uses imghdr to inspect bytes first; falls back to MIME string like 'image/jpeg'.
    """
    detected = imghdr.what(None, h=image_bytes)  # returns 'png', 'jpeg', 'gif', etc. or None
    if detected:
        # imghdr returns 'jpeg' for JPEGs (Bedrock expects 'jpeg' or 'png')
        return detected
    # fallback: fallback_mime might be like 'image/jpeg'
    if fallback_mime:
        try:
            return fallback_mime.split("/", 1)[1]
        except Exception:
            pass
    # ultimate fallback
    return "png"

def _convert_bytes_to_png(image_bytes: bytes) -> bytes:
    """
    Convert image bytes (jpeg, gif, etc.) to PNG bytes using Pillow.
    Raises RuntimeError with guidance if Pillow isn't available.
    """
    try:
        from PIL import Image
    except Exception as e:
        raise RuntimeError(
            "Pillow is required for converting images to PNG. "
            "Install it in your environment (pip install pillow) or send PNG bytes from the client."
        ) from e

    buf = io.BytesIO(image_bytes)
    img = Image.open(buf)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()

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


def analyze_snapshot_with_nova(image_bytes: bytes, ticket_suggestion: str, declared_format: str = None, force_png: bool = False):
    """
    Build the Bedrock messages-v1 multimodal payload.
    - If declared_format is given, it will be used only if it matches detected type.
    - If force_png is True and bytes are not PNG, attempt to convert to PNG (requires Pillow).
    """
    # detect format from bytes (imghdr) or fallback to declared_format
    detected_format = _detect_image_format_from_bytes(image_bytes, fallback_mime=declared_format)

    # If caller insists on PNG, convert if necessary
    if force_png and detected_format != "png":
        image_bytes = _convert_bytes_to_png(image_bytes)
        detected_format = "png"

    # Base64 encode the (possibly converted) image for the InvokeModel JSON body
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    system_list = [
        {
            "text": (
                "You are an IT support assistant. Given a screenshot, provide "
                "precise, concise instructions on where to click or which menu to use."
            )
        }
    ]

    message_list = [
        {
            "role": "user",
            "content": [
                {
                    "image": {
                        # Use the detected format so Bedrock validation matches the bytes
                        "format": detected_format,
                        "source": {
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
        "schemaVersion": "messages-v1",
        "system": system_list,
        "messages": message_list,
        "inferenceConfig": {"maxTokens": MAX_TOKENS, "temperature": TEMPERATURE},
    }

    try:
        response = bedrock_client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(native_request),
        )
    except ClientError as e:
        raise RuntimeError(f"Bedrock invoke_model failed: {e}") from e

    try:
        raw = response["body"].read()
        model_response = json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"Failed to parse Bedrock response: {e}\nRaw: {raw[:2000]}") from e

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
        # header example: "data:image/jpeg;base64"
        # Extract mime (e.g., "image/jpeg") if present
        mime = None
        if header.startswith("data:"):
            parts = header[5:].split(";")
            if parts:
                mime = parts[0]  # e.g., "image/jpeg"
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
        # Analyze with Bedrock
    try:
        # If you prefer to always send PNGs to Bedrock, set force_png=True (requires Pillow)
        suggestion = analyze_snapshot_with_nova(image_bytes, ticket_suggestion, declared_format=mime, force_png=False)
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
