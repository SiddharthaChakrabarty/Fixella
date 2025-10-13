#!/usr/bin/env python3
"""
test_single_ticket.py

Single-ticket test harness (hardcoded sample ticket).

This version downloads the model from S3 by default (unless --model-path is provided).
It includes the small custom transformers used by the pipeline so joblib.load can unpickle.
"""

import os
import sys
import argparse
import json
import tarfile
import tempfile
from datetime import datetime
import joblib
import pandas as pd

# Optional S3 support
try:
    import boto3
except Exception:
    boto3 = None

# ---------- DEFAULT S3 model location (change if needed) ----------
S3_BUCKET_DEFAULT = "fixella-bucket-superhack"
MODEL_S3_KEY_DEFAULT = "models/ticket_escalation_model.joblib"  # or models/ticket_escalation_model.tar.gz

# ----------------- Hardcoded example ticket (unchanged format) -----------------
EXAMPLE_TICKET = {
    "ticketId": "9112880565763052729",
    "displayId": "6",
    "subject": "Unable to login to email",
    "ticketType": "INCIDENT",
    "requestType": "Incident",
    "source": "FORM",
    "client": {
      "accountId": "6028532731226112000",
      "name": "Dunder Mifflin"
    },
    "site": {
      "id": "6028532731314192384",
      "name": "Scranton HQ"
    },
    "requester": {
      "userId": "6049390062889756912",
      "name": "Dwight Schrute"
    },
    "additionalRequester": [],
    "followers": [],
    "technician": {
      "userId": "83352153327464448",
      "name": "Sneha Jain"
    },
    "status": "Closed",
    "priority": None,
    "impact": "Medium",
    "urgency": "Medium",
    "category": "Software",
    "subcategory": "VPN",
    "cause": "Capacity related",
    "subcause": "User",
    "resolutionCode": None,
    "sla": None,
    "createdTime": "2025-10-08T20:59:02.268676",
    "updatedTime": "2025-10-08T20:59:02.268676",
    "firstResponseDueTime": None,
    "firstResponseTime": None,
    "resolutionDueTime": None,
    "resolutionTime": None,
    "resolutionViolated": False,
    "customFields": {
      "udf3num": None,
      "udf4text": None,
      "udf2select": None
    },
    "worklogTimespent": "0.00",
    "resolutionSteps": [
      "Verified username and password.",
      "Reset password via self-service portal.",
      "Checked account lockout status.",
      "Cleared browser cache and cookies.",
      "Tested login on different browser/device.",
      "Issue resolved after password reset."
    ]
  }

# ------------------ Ensure custom transformers are present for unpickling ------------------
# These names must match exactly the classes used when saving the model.
from sklearn.base import BaseEstimator, TransformerMixin

class TextSelector(BaseEstimator, TransformerMixin):
    """Select a text column for vectorizers (used at training)."""
    def __init__(self, key):
        self.key = key
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        # X is expected to be a DataFrame
        try:
            return X[self.key].fillna("").astype(str).values
        except Exception:
            # fallback if X is list-of-dicts
            return pd.Series([str(x.get(self.key, "")) for x in X]).values

class ColumnSelector(BaseEstimator, TransformerMixin):
    """Select columns and return DataFrame/Numpy array for downstream transformers."""
    def __init__(self, keys):
        self.keys = keys
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        try:
            return X[self.keys]
        except Exception:
            # fallback for list-of-dicts
            return pd.DataFrame(X)[self.keys]

# ----------------- Helpers (matching training code) -----------------
def parse_iso(ts):
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        from datetime import datetime as _dt
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                return _dt.strptime(ts, fmt)
            except Exception:
                pass
    return None

def flatten_ticket(ticket: dict) -> dict:
    flat = {}
    flat["ticketId"] = ticket.get("ticketId")
    flat["displayId"] = ticket.get("displayId")
    flat["subject"] = (ticket.get("subject") or "").strip()
    flat["resolution_text"] = " ".join(ticket.get("resolutionSteps") or [])
    flat["ticketType"] = ticket.get("ticketType")
    flat["requestType"] = ticket.get("requestType")
    flat["source"] = ticket.get("source")
    flat["client_name"] = (ticket.get("client") or {}).get("name")
    flat["site_name"] = (ticket.get("site") or {}).get("name")
    flat["requester_name"] = (ticket.get("requester") or {}).get("name")
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
    try:
        flat["worklogTimespent"] = float(ticket.get("worklogTimespent") or 0.0)
    except Exception:
        flat["worklogTimespent"] = 0.0
    flat["followers_count"] = len(ticket.get("followers") or [])
    created = parse_iso(ticket.get("createdTime"))
    flat["createdTime"] = created
    flat["created_hour"] = created.hour if created else -1
    flat["created_weekday"] = created.weekday() if created else -1
    flat["subject_len"] = len(flat["subject"])
    flat["resolution_len"] = len(flat["resolution_text"])
    flat["has_followers"] = int(flat["followers_count"] > 0)
    return flat

def label_escalation(flat_ticket: dict, escalation_marker: str = "escalation") -> int:
    tg = (flat_ticket.get("techgroup_name") or "").lower()
    return int(escalation_marker.lower() in tg)

def prepare_single_dataframe(ticket: dict) -> pd.DataFrame:
    flat = flatten_ticket(ticket)
    flat["priority"] = flat.get("priority") or "Unknown"
    flat["impact"] = flat.get("impact") or "Unknown"
    flat["urgency"] = flat.get("urgency") or "Unknown"
    flat["category"] = flat.get("category") or "Unknown"
    flat["subcategory"] = flat.get("subcategory") or "Unknown"
    flat["technician_name"] = flat.get("technician_name") or "Unknown"
    for c in ["followers_count", "worklogTimespent", "created_hour", "created_weekday", "subject_len", "resolution_len", "has_followers"]:
        if c not in flat:
            flat[c] = 0
    df = pd.DataFrame([flat])
    return df

# ----------------- Model S3 utilities -----------------
def download_from_s3(bucket, key, local_path):
    if boto3 is None:
        raise RuntimeError("boto3 not available in this environment to download from S3.")
    s3 = boto3.client("s3")
    print(f"Downloading s3://{bucket}/{key} -> {local_path}")
    s3.download_file(bucket, key, local_path)
    return local_path

def extract_joblib_from_tar(tar_path, dest_dir):
    """If tar contains a .joblib file, extract and return its path. Otherwise return None."""
    with tarfile.open(tar_path, "r:*") as tf:
        members = tf.getmembers()
        joblib_candidates = [m for m in members if m.name.endswith(".joblib")]
        if joblib_candidates:
            # take first candidate
            member = joblib_candidates[0]
            tf.extract(member, path=dest_dir)
            extracted_path = os.path.join(dest_dir, member.name)
            return extracted_path
    return None

def load_model(model_path=None, s3_bucket=None, s3_key=None):
    """
    Load model either from local path (preferred) or download from S3.
    If downloaded file is a tarball, attempt to extract a .joblib inside.
    """
    # priority: explicit local path
    if model_path:
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Provided model path does not exist: {model_path}")
        print(f"Loading model from local path: {model_path}")
        return joblib.load(model_path)

    # else prefer S3 download
    if s3_bucket is None:
        s3_bucket = S3_BUCKET_DEFAULT
    if s3_key is None:
        s3_key = MODEL_S3_KEY_DEFAULT

    if boto3 is None:
        raise RuntimeError("boto3 is required to download model from S3 but is not available.")

    # download to temporary location
    tmp_dir = tempfile.mkdtemp()
    local_file = os.path.join(tmp_dir, os.path.basename(s3_key))
    download_from_s3(s3_bucket, s3_key, local_file)

    # if it's a tar.gz archive, extract .joblib inside
    if tarfile.is_tarfile(local_file) or local_file.endswith(".tar.gz") or local_file.endswith(".tgz"):
        print("Downloaded artifact appears to be a tarball; attempting to extract .joblib inside.")
        extracted = extract_joblib_from_tar(local_file, tmp_dir)
        if extracted:
            print("Extracted joblib:", extracted)
            return joblib.load(extracted)
        else:
            # fallback: try extracting whole tar and search for common model name
            print("No .joblib found inside tarball. Listing contents for debugging:")
            with tarfile.open(local_file, "r:*") as tf:
                for m in tf.getmembers():
                    print(" -", m.name)
            raise FileNotFoundError("No .joblib file found inside the downloaded tarball.")
    else:
        # assume it's a joblib / pickle file
        print("Downloaded model file:", local_file)
        return joblib.load(local_file)

# ----------------- Inference -----------------
def run_single_prediction(pipeline, ticket: dict):
    df = prepare_single_dataframe(ticket)
    feature_cols = [
        "subject", "resolution_text",
        "priority", "impact", "urgency", "category", "subcategory", "technician_name",
        "followers_count", "worklogTimespent", "created_hour", "created_weekday",
        "subject_len", "resolution_len", "has_followers"
    ]
    for c in feature_cols:
        if c not in df.columns:
            df[c] = None

    X = df[feature_cols]
    print("\nInput features (prepared for model):")
    displayable = X.to_dict(orient="records")[0]
    if "resolution_text" in displayable and isinstance(displayable["resolution_text"], str):
        displayable["resolution_text"] = (displayable["resolution_text"][:250] + "...") if len(displayable["resolution_text"]) > 250 else displayable["resolution_text"]
    if "subject" in displayable and isinstance(displayable["subject"], str):
        displayable["subject"] = (displayable["subject"][:200] + "...") if len(displayable["subject"]) > 200 else displayable["subject"]
    print(json.dumps(displayable, indent=2))

    try:
        pred = pipeline.predict(X)[0]
    except Exception as e:
        print("Error during pipeline.predict:", e)
        raise

    print("\nPredicted class (0 = not escalated, 1 = escalated):", int(pred))

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

    try:
        print("\nLoaded pipeline steps (summary):")
        if hasattr(pipeline, "steps"):
            print([ (name, type(step).__name__) for name, step in pipeline.steps ])
        else:
            print(type(pipeline))
    except Exception:
        pass

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
    print("\nResult summary:")
    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    main()
