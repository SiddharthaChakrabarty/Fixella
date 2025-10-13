#!/usr/bin/env python3
"""
test_single_ticket.py

Single-ticket test harness (hardcoded sample ticket).

This version is adapted to the improved pipeline:
- Model expects separate 'subject' and 'resolution_text' TF-IDF features,
  plus categorical and numeric features such as subject_len, resolution_len, has_followers, etc.
- The test ticket format is NOT changed (your JSON structure remains the same).

Usage:
  # Use local model (default looks for /tmp/ticket_escalation_model.joblib or ./ticket_escalation_model.joblib)
  python test_single_ticket.py

  # Specify local model explicitly
  python test_single_ticket.py --model-path ./ticket_escalation_model.joblib

  # Download model from S3 (requires boto3 and IAM permissions)
  python test_single_ticket.py --s3-bucket my-bucket --model-key models/ticket_escalation_model.joblib
"""

import os
import sys
import argparse
import json
from datetime import datetime
import joblib
import pandas as pd

# Optional S3 support
try:
    import boto3
except Exception:
    boto3 = None

# ----------------- Hardcoded example ticket (unchanged format) -----------------
EXAMPLE_TICKET = {
    "ticketId": "4455667788990011229",
    "displayId": "266",
    "subject": "WiFi connection issues",
    "ticketType": "INCIDENT",
    "requestType": "Incident",
    "source": "FORM",
    "client": {
      "accountId": "6028538986002923520",
      "name": "Globex Corporation"
    },
    "site": {
      "id": "6028538986044866560",
      "name": "Globe Town"
    },
    "requester": {
      "userId": "6028539118144471040",
      "name": "Winslow Jay"
    },
    "additionalRequester": [],
    "followers": [
      {
        "userId": "6888345609010850595",
        "name": "Pam Beesly"
      }
    ],
    "technician": {
      "userId": "83352153327464448",
      "name": "Siddhartha Chakrabarty"
    },
    "status": "Resolved",
    "priority": "Medium",
    "impact": "Medium",
    "urgency": "Medium",
    "category": "Network",
    "subcategory": "WiFi",
    "cause": "Power cycle needed",
    "subcause": "Hardware",
    "resolutionCode": None,
    "sla": None,
    "createdTime": "2025-10-12T01:20:00.000",
    "updatedTime": "2025-10-12T02:00:00.000",
    "firstResponseDueTime": None,
    "firstResponseTime": "2025-10-12T01:25:00.000",
    "resolutionDueTime": None,
    "resolutionTime": "2025-10-12T02:00:00.000",
    "resolutionViolated": False,
    "customFields": {
      "udf3num": None,
      "udf4text": None,
      "udf2select": None
    },
    "worklogTimespent": "0.67",
    "resolutionSteps": [
      "Restarted WiFi router.",
      "Forgot network and reconnected.",
      "Checked WiFi signal strength.",
      "Updated WiFi adapter drivers.",
      "Changed WiFi channel to avoid interference.",
      "Connection stabilized after router restart."
    ]
  }

from sklearn.base import BaseEstimator, TransformerMixin

class TextSelector(BaseEstimator, TransformerMixin):
    def __init__(self, key):
        self.key = key
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        return X[self.key].fillna("").astype(str).values

class ColumnSelector(BaseEstimator, TransformerMixin):
    def __init__(self, keys):
        self.keys = keys
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        return X[self.keys]

# ----------------- Helpers (must match training code) -----------------
def parse_iso(ts):
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        # Python 3.7+ supports many ISO formats
        return datetime.fromisoformat(ts)
    except Exception:
        # Fallback common formats
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(ts, fmt)
            except Exception:
                pass
    return None

def flatten_ticket(ticket: dict) -> dict:
    """
    Flatten the incoming ticket JSON into the feature fields expected by the improved pipeline.
    This keeps the original ticket JSON format untouched.
    """
    flat = {}
    flat["ticketId"] = ticket.get("ticketId")
    flat["displayId"] = ticket.get("displayId")
    flat["subject"] = (ticket.get("subject") or "").strip()
    # resolutionSteps -> resolution_text (joined)
    flat["resolution_text"] = " ".join(ticket.get("resolutionSteps") or [])
    flat["ticketType"] = ticket.get("ticketType")
    flat["requestType"] = ticket.get("requestType")
    flat["source"] = ticket.get("source")
    flat["client_name"] = (ticket.get("client") or {}).get("name")
    flat["site_name"] = (ticket.get("site") or {}).get("name")
    flat["requester_name"] = (ticket.get("requester") or {}).get("name")
    # techGroup may be missing in test tickets; we DO NOT use techGroup as an input feature
    tg = ticket.get("techGroup") or {}
    flat["techgroup_id"] = tg.get("groupId")
    flat["techgroup_name"] = tg.get("name")
    flat["technician_name"] = (ticket.get("technician") or {}).get("name")
    flat["status"] = ticket.get("status")
    flat["priority"] = ticket.get("priority")
    flat["impact"] = ticket.get("impact")
    flat["urgency"] = ticket.get("urgency")
    flat["category"] = ticket.get("category")
    flat["subcategory"] = ticket.get("subcategory")
    flat["cause"] = ticket.get("cause")
    flat["subcause"] = ticket.get("subcause")
    flat["resolutionViolated"] = bool(ticket.get("resolutionViolated"))
    # numeric conversion
    try:
        flat["worklogTimespent"] = float(ticket.get("worklogTimespent") or 0.0)
    except Exception:
        flat["worklogTimespent"] = 0.0
    # followers
    flat["followers_count"] = len(ticket.get("followers") or [])
    # timestamps
    created = parse_iso(ticket.get("createdTime"))
    flat["createdTime"] = created
    flat["created_hour"] = created.hour if created else -1
    flat["created_weekday"] = created.weekday() if created else -1
    # derived features
    flat["subject_len"] = len(flat["subject"])
    flat["resolution_len"] = len(flat["resolution_text"])
    flat["has_followers"] = int(flat["followers_count"] > 0)
    return flat

def label_escalation(flat_ticket: dict, escalation_marker: str = "escalation") -> int:
    # This helper replicates the simple rule (used only for optional display)
    tg = (flat_ticket.get("techgroup_name") or "").lower()
    return int(escalation_marker.lower() in tg)

def prepare_single_dataframe(ticket: dict) -> pd.DataFrame:
    """
    Build a dataframe matching the improved pipeline's expected features.
    The ticket JSON format is unchanged; this function extracts and computes the required features.
    """
    flat = flatten_ticket(ticket)
    # fill categorical defaults exactly as training did
    flat["priority"] = flat.get("priority") or "Unknown"
    flat["impact"] = flat.get("impact") or "Unknown"
    flat["urgency"] = flat.get("urgency") or "Unknown"
    flat["category"] = flat.get("category") or "Unknown"
    flat["subcategory"] = flat.get("subcategory") or "Unknown"
    flat["technician_name"] = flat.get("technician_name") or "Unknown"
    # ensure numeric fields present
    for c in ["followers_count", "worklogTimespent", "created_hour", "created_weekday", "subject_len", "resolution_len", "has_followers"]:
        if c not in flat:
            flat[c] = 0
    df = pd.DataFrame([flat])
    return df

# ----------------- Model loading -----------------
def download_from_s3(bucket, key, local_path):
    if boto3 is None:
        raise RuntimeError("boto3 not available in this environment to download from S3.")
    s3 = boto3.client("s3")
    print(f"Downloading s3://{bucket}/{key} -> {local_path}")
    s3.download_file(bucket, key, local_path)
    return local_path

def load_model(model_path=None, s3_bucket=None, s3_key=None):
    tried = []
    if s3_bucket and s3_key:
        # download into /tmp
        local_tmp = os.path.join("/tmp", os.path.basename(s3_key))
        download_from_s3(s3_bucket, s3_key, local_tmp)
        model_path = local_tmp

    if model_path and os.path.exists(model_path):
        print(f"Loading model from local path: {model_path}")
        return joblib.load(model_path)

    # fallback candidates
    for candidate in ["./ticket_escalation_model.joblib", "/tmp/ticket_escalation_model.joblib", "/tmp/ticket_escalation_model.joblib", "/tmp/ticket_escalation_model.joblib"]:
        tried.append(candidate)
        if os.path.exists(candidate):
            print(f"Loading model from: {candidate}")
            return joblib.load(candidate)

    # also try the path used in your earlier script
    default_candidate = "/tmp/ticket_escalation_model.joblib"
    tried.append(default_candidate)
    if os.path.exists(default_candidate):
        return joblib.load(default_candidate)

    raise FileNotFoundError(
        "Model not found. Provide --model-path or --s3-bucket/--model-key. Tried: " + ", ".join(tried)
    )

# ----------------- Inference -----------------
def run_single_prediction(pipeline, ticket: dict):
    df = prepare_single_dataframe(ticket)
    # feature column list for the improved pipeline
    feature_cols = [
        "subject", "resolution_text",
        "priority", "impact", "urgency", "category", "subcategory", "technician_name",
        "followers_count", "worklogTimespent", "created_hour", "created_weekday",
        "subject_len", "resolution_len", "has_followers"
    ]
    # ensure all expected columns exist in df
    for c in feature_cols:
        if c not in df.columns:
            df[c] = None

    X = df[feature_cols]
    print("\nInput features (prepared for model):")
    # show a compact representation
    displayable = X.to_dict(orient="records")[0]
    # hide extremely long text by truncating for display
    if "resolution_text" in displayable and isinstance(displayable["resolution_text"], str):
        displayable["resolution_text"] = (displayable["resolution_text"][:250] + "...") if len(displayable["resolution_text"]) > 250 else displayable["resolution_text"]
    if "subject" in displayable and isinstance(displayable["subject"], str):
        displayable["subject"] = (displayable["subject"][:200] + "...") if len(displayable["subject"]) > 200 else displayable["subject"]
    print(json.dumps(displayable, indent=2))

    # predict
    try:
        pred = pipeline.predict(X)[0]
    except Exception as e:
        print("Error during pipeline.predict:", e)
        raise

    print("\nPredicted class (0 = not escalated, 1 = escalated):", int(pred))

    # probability if available
    prob1 = None
    try:
        if hasattr(pipeline, "predict_proba"):
            prob = pipeline.predict_proba(X)[0]
            prob1 = float(prob[1]) if len(prob) > 1 else None
            print("Predicted probability (class=1):", prob1)
        else:
            print("predict_proba not available for this model.")
    except Exception as e:
        print("predict_proba error (model may not support it):", e)

    # print pipeline steps if present
    try:
        print("\nLoaded pipeline steps (summary):")
        if hasattr(pipeline, "steps"):
            print([ (name, type(step).__name__) for name, step in pipeline.steps ])
        else:
            print(type(pipeline))
    except Exception:
        pass

    # optional: show derived 'true' escalation label by simple rule (uses techGroup if present)
    true_label = label_escalation(flatten_ticket(ticket))
    print("\nRule-based 'true' label (techGroup contains 'escalation'):", true_label)
    return {"prediction": int(pred), "probability_class1": prob1, "input": displayable, "rule_label": true_label}

# ----------------- CLI and main -----------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", help="Local path to joblib model", default=None)
    parser.add_argument("--s3-bucket", help="S3 bucket (optional)", default=None)
    parser.add_argument("--model-key", help="S3 key for model (optional)", default=None)
    parser.add_argument("--use-example", action="store_true",
                        help="If set, will print the hardcoded example ticket JSON as well.")
    args = parser.parse_args()

    try:
        pipeline = load_model(model_path=args.model_path, s3_bucket=args.s3_bucket, s3_key=args.model_key)
    except Exception as e:
        print("ERROR loading model:", e)
        sys.exit(2)

    if args.use_example:
        print("\n--- Example ticket JSON (original format) ---")
        print(json.dumps(EXAMPLE_TICKET, indent=2))

    result = run_single_prediction(pipeline, EXAMPLE_TICKET)
    # Print a compact result
    print("\nResult summary:")
    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    main()
