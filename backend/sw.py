# app.py
import os
import json
import threading
import time
from typing import Any, Dict, List, Optional
from flask import Flask, jsonify, request
from flask_cors import CORS  # Add this import
from dotenv import load_dotenv
from botocore.exceptions import ClientError

# local helper (import or inline)
from ingest_s3 import fetch_kb_from_s3  # assuming ingest_s3.py is next to this file

load_dotenv()

# Configuration (via env or .env)
S3_BUCKET = "fixella-bucket-superhack"  # e.g. "my-kb-bucket" ; optional
S3_KEY = "it_tickets_kb.json"
AWS_REGION = "us-east-1"  # optional
LOCAL_FALLBACK = os.path.join(os.path.dirname(__file__), "..", "it_tickets_kb.json")
# normalize path
LOCAL_FALLBACK = os.path.abspath(LOCAL_FALLBACK)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# in-memory DB
TICKETS_LOCK = threading.Lock()
TICKETS: List[Dict[str, Any]] = []
LAST_UPDATED: Optional[float] = None  # epoch seconds


def load_kb_from_local(path: str) -> List[Dict[str, Any]]:
    """Read KB from a local file path. If file missing, return empty list."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def reload_kb_from_s3_or_local() -> Dict[str, Any]:
    """
    Try to fetch KB from S3 (if configured). On S3 failure, fall back to local file.
    Returns a status dict with metadata.
    """
    global TICKETS, LAST_UPDATED
    fetched_from = "none"
    kb = None
    # attempt S3 if configured
    if S3_BUCKET:
        try:
            kb = fetch_kb_from_s3(S3_BUCKET, S3_KEY, AWS_REGION)
            fetched_from = f"s3://{S3_BUCKET}/{S3_KEY}"
            # optionally write a local cache fallback
            try:
                os.makedirs(os.path.dirname(LOCAL_FALLBACK), exist_ok=True)
                with open(LOCAL_FALLBACK, "w", encoding="utf-8") as f:
                    json.dump(kb, f, ensure_ascii=False, indent=2)
            except Exception:
                # don't fail the whole operation if cache write fails
                pass
        except ClientError as ce:
            fetched_from = f"s3-error: {str(ce)}"
            kb = None
        except Exception as e:
            fetched_from = f"s3-error: {str(e)}"
            kb = None

    # if S3 didn't yield KB, try local fallback
    if kb is None:
        try:
            kb = load_kb_from_local(LOCAL_FALLBACK)
            if kb:
                fetched_from = LOCAL_FALLBACK
        except Exception as e:
            kb = []
            fetched_from = f"local-error: {str(e)}"

    # final fallback to empty list
    if kb is None:
        kb = []

    # write into in-memory DB (thread-safe)
    with TICKETS_LOCK:
        TICKETS = kb
        LAST_UPDATED = time.time()

    return {"count": len(kb), "source": fetched_from, "last_updated": LAST_UPDATED}


# Load at startup (blocking)
startup_info = reload_kb_from_s3_or_local()
print("Startup KB load:", startup_info)


@app.route("/health")
def health():
    with TICKETS_LOCK:
        return jsonify(
            {"ok": True, "tickets_loaded": len(TICKETS), "last_updated": LAST_UPDATED}
        )


@app.route("/tickets")
def tickets():
    # Return all tickets (same shape as original app expected)
    with TICKETS_LOCK:
        # return a shallow copy to avoid accidental external mutation
        return jsonify(list(TICKETS))


@app.route("/refresh", methods=["POST", "GET"])
def refresh():
    """
    Force reload of the KB from S3 (if configured) or local file.
    This endpoint allows you to trigger re-ingestion without restarting Flask.
    """
    result = reload_kb_from_s3_or_local()
    return jsonify(result)


if __name__ == "__main__":
    # dev server
    debug = os.getenv("FLASK_DEBUG", "1") not in ("0", "false", "no")
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    app.run(debug=debug, host=host, port=port)
