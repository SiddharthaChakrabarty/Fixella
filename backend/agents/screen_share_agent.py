# ### FILE: strands_bedrock_agent.py
"""
Strands-based wrapper around Bedrock multimodal operations. This module exposes two functions
with the same signatures used in the original backend_server.py:

- analyze_snapshot_for_completion(image_bytes: bytes, substep_text: str, declared_format: str = None, force_png: bool = False)
- generate_where_to_go_from_snapshot(image_bytes: bytes, substep_text: str, declared_format: str = None) -> str

This version fixes the reliability problems by invoking Bedrock via the native
`boto3` bedrock-runtime.invoke_model API (messages-v1 multimodal schema) instead of
embedding the base64 image directly into a plain-text agent prompt.

It also exposes a small Strands @tool wrapper (bedrock_invoke_multimodal) so you can
use it as a tool if you want the Agent to call it. However the high-level functions
below call the tool directly to keep behavior identical to your original working flow.
"""
import os
import json
import base64
import re
import imghdr
from typing import Optional, Dict, Any

import boto3  # type: ignore
from botocore.exceptions import ClientError  # type: ignore

# strands imports (tool decorator is convenient if you later want an Agent to call the tool)
from strands import tool  # type: ignore
from strands import Agent  # type: ignore
from strands.models import BedrockModel  # type: ignore

# ----------------- Configuration -----------------
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "256"))
TEMPERATURE = float(os.environ.get("BEDROCK_TEMPERATURE", "0.0"))
TOP_P = float(os.environ.get("BEDROCK_TOP_P", "0.1"))

# boto3 client for native multimodal invoke (used by the tool)
bedrock_client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)


def _detect_image_format_from_bytes(image_bytes: bytes, fallback_mime: Optional[str] = None) -> str:
    """
    Return a short format string suitable for Bedrock's 'format' (e.g. 'png', 'jpeg', 'webp').
    Uses imghdr to inspect bytes first; falls back to MIME string like 'image/jpeg'.
    """
    detected = imghdr.what(None, h=image_bytes)
    if detected:
        return detected
    if fallback_mime:
        try:
            return fallback_mime.split("/", 1)[1]
        except Exception:
            pass
    return "png"


def _safe_extract_text(model_response: Dict[str, Any]) -> str:
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
        # fallback: small dump
        try:
            return json.dumps(model_response)[:4000]
        except Exception:
            return str(model_response)


@tool(
    name="bedrock_invoke_multimodal",
    description="Invoke Bedrock multimodal using the messages-v1 JSON payload. Returns parsed model JSON."
)
def bedrock_invoke_multimodal(native_request: Dict[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
    """
    native_request: dict already shaped like messages-v1 (system, messages, inferenceConfig).
    model_id: optional override for modelId.
    Returns the parsed JSON response from Bedrock or a dict with '__error__' on failure.
    """
    model_to_use = model_id or BEDROCK_MODEL_ID

    # Ensure inference config defaults if not present:
    if "inferenceConfig" not in native_request:
        native_request["inferenceConfig"] = {
            "maxTokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "topP": TOP_P,
        }

    try:
        resp = bedrock_client.invoke_model(
            modelId=model_to_use,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(native_request),
        )
        raw = resp["body"].read()
        return json.loads(raw)
    except ClientError as e:
        return {"__error__": f"AWS ClientError: {e}"}
    except Exception as e:
        return {"__error__": f"InvokeModel error: {e}"}


# Optionally initialize a BedrockModel for agent orchestration (not required by the direct calls below)
bedrock_model = BedrockModel(
    model_id=BEDROCK_MODEL_ID,
    temperature=TEMPERATURE,
    max_tokens=MAX_TOKENS,
    region_name=BEDROCK_REGION,
)

# Example small agents (optional, they are not used to carry image data inside free text)
visual_system = (
    "You are a highly consistent visual verification assistant. Your task: examine a screenshot and answer a "
    "simple YES/NO completion question, returning EXACTLY two lines (Line1: 'YES' or 'NO', Line2: a short evidence sentence)."
)
visual_agent = Agent(model=bedrock_model, tools=[bedrock_invoke_multimodal], system_prompt=visual_system)

where_system = (
    "You are a concise UI path extraction assistant. Given a screenshot and a short substep, return a single short UI path line."
)
where_agent = Agent(model=bedrock_model, tools=[bedrock_invoke_multimodal], system_prompt=where_system)


def analyze_snapshot_for_completion(
    image_bytes: bytes,
    substep_text: str,
    declared_format: str = None,
    force_png: bool = False
) -> Dict[str, Any]:
    """
    Build the same Bedrock 'messages-v1' multimodal request used in the original working code,
    call bedrock_invoke_multimodal (native invoke) and parse the strict two-line YES/NO response.

    Returns a dict: { "decision": "YES"|"NO", "explanation": "<short evidence>", "raw": <model_response_json> }
    """
    detected_format = _detect_image_format_from_bytes(image_bytes, fallback_mime=declared_format)
    if force_png:
        detected_format = "png"

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
                        "Remember: respond only as per the format described. Do not justify beyond a single evidence sentence."
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
            "temperature": TEMPERATURE,
            "topP": TOP_P,
        },
    }

    # Call Bedrock via the tool (direct function call)
    model_response = bedrock_invoke_multimodal(native_request)
    # If the tool returned an error dict, surface it in the raw and fallback
    if isinstance(model_response, dict) and model_response.get("__error__"):
        # try one more time (retry) like original fallback logic
        model_response_retry = bedrock_invoke_multimodal(native_request)
        if model_response_retry and not model_response_retry.get("__error__"):
            model_response = model_response_retry

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
        model_response2 = bedrock_invoke_multimodal(native_request)
        # if error, return NO with explanation
        if isinstance(model_response2, dict) and model_response2.get("__error__"):
            return {
                "decision": "NO",
                "explanation": model_response2.get("__error__"),
                "raw": model_response2,
            }

        text2 = _safe_extract_text(model_response2) or ""
        lines2 = [ln.strip() for ln in text2.splitlines() if ln.strip()]
        first2 = lines2[0].split()[0].upper() if lines2 else ""
        if first2 == "YES":
            decision = "YES"
        elif first2 == "NO":
            decision = "NO"
        if len(lines2) > 1:
            explanation = lines2[1]
        model_response = model_response2

    if decision not in ("YES", "NO"):
        decision = "NO"
        explanation = explanation or "Unclear or ambiguous output from model."

    return {
        "decision": decision,
        "explanation": explanation,
        "raw": model_response,
    }


def generate_where_to_go_from_snapshot(image_bytes: bytes, substep_text: str, declared_format: str = None) -> str:
    """
    Use Bedrock native multimodal invoke (messages-v1) to ask for a short 'whereToGo' UI path line.
    Returns the first non-empty sanitized line or 'Unknown'.
    """
    detected_format = _detect_image_format_from_bytes(image_bytes, fallback_mime=declared_format)
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    system_list = [
        {
            "text": (
                "You are a concise UI path extraction assistant. "
                "Given a screenshot (image) showing the current UI and a short substep description, "
                "output a single short `whereToGo` string describing where in the UI to perform the action. "
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
        "inferenceConfig": {"maxTokens": 60, "temperature": TEMPERATURE, "topP": TOP_P},
    }

    try:
        model_response = bedrock_invoke_multimodal(native_request)
        if isinstance(model_response, dict) and model_response.get("__error__"):
            return "Unknown"
        text = _safe_extract_text(model_response) or ""
        for ln in text.splitlines():
            ln = ln.strip()
            if ln:
                ln = re.sub(r"^Where:\s*", "", ln, flags=re.IGNORECASE)
                if len(ln) > 200:
                    ln = ln[:200]
                return ln
        return "Unknown"
    except Exception:
        return "Unknown"


# Exported symbols
__all__ = [
    "analyze_snapshot_for_completion",
    "generate_where_to_go_from_snapshot",
    "bedrock_invoke_multimodal",
]
