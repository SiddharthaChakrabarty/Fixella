# inference.py
import os
import sys
import json
import joblib
import boto3
import tempfile
import logging
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

# Logging setup
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# -------------------------
# Custom transformer stubs
# -------------------------
class TextSelector(BaseEstimator, TransformerMixin):
    def __init__(self, key):
        self.key = key
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        try:
            series = X[self.key].fillna("").astype(str)
            return series.values
        except Exception:
            try:
                return pd.Series([str(x.get(self.key, "")) for x in X]).values
            except Exception:
                return np.array([ "" for _ in range(len(X)) ])

class ColumnSelector(BaseEstimator, TransformerMixin):
    def __init__(self, keys):
        self.keys = keys
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        try:
            return X[self.keys]
        except Exception:
            return pd.DataFrame(X)[self.keys]

# Ensure classes are resolvable during unpickle if saved under __main__
_main = sys.modules.get("__main__")
if _main is not None:
    setattr(_main, "TextSelector", TextSelector)
    setattr(_main, "ColumnSelector", ColumnSelector)

# -------------------------
# Feature helpers
# -------------------------
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
    # Fill defaults used during training
    flat["priority"] = flat.get("priority") or "Unknown"
    flat["impact"] = flat.get("impact") or "Unknown"
    flat["urgency"] = flat.get("urgency") or "Unknown"
    flat["category"] = flat.get("category") or "Unknown"
    flat["subcategory"] = flat.get("subcategory") or "Unknown"
    flat["technician_name"] = flat.get("technician_name") or "Unknown"
    return flat

# -------------------------
# Model load helpers
# -------------------------
def _download_s3_uri_to_local(s3_uri: str, local_path: str):
    if not s3_uri:
        raise ValueError("s3_uri is empty")
    if s3_uri.startswith("s3://"):
        _, _, rest = s3_uri.partition("s3://")
        parts = rest.split("/", 1)
        if len(parts) != 2:
            raise ValueError("Invalid s3 uri: " + s3_uri)
        bucket, key = parts
    else:
        parts = s3_uri.split("/", 1)
        if len(parts) != 2:
            raise ValueError("Invalid s3 uri: " + s3_uri)
        bucket, key = parts
    logger = logging.getLogger(__name__)
    logger.info("Downloading model from S3: s3://%s/%s -> %s", bucket, key, local_path)
    s3 = boto3.client("s3")
    s3.download_file(bucket, key, local_path)
    return local_path

_model = None

def model_fn(model_dir):
    """
    SageMaker calls this to load the model. Search typical names and also allow
    MODEL_S3_URI environment variable as fallback to download a .joblib from S3.
    """
    global _model
    if _model is not None:
        return _model

    logger.info("Attempting to load model from model_dir: %s", model_dir)
    candidates = [
        os.path.join(model_dir, "model.joblib"),
        os.path.join(model_dir, "model.pkl"),
        os.path.join(model_dir, "ticket_escalation_model.joblib"),
        os.path.join(model_dir, "ticket_escalation_model.pkl"),
    ]

    found = None
    for p in candidates:
        if p and os.path.exists(p):
            found = p
            break

    # If not found, allow MODEL_S3_URI env var (e.g. s3://bucket/path/to/joblib)
    if not found:
        s3_uri = os.environ.get("MODEL_S3_URI") or os.environ.get("MODEL_S3_PATH")
        if s3_uri:
            tmpf = os.path.join(tempfile.gettempdir(), os.path.basename(s3_uri))
            try:
                _download_s3_uri_to_local(s3_uri, tmpf)
                found = tmpf
            except Exception as e:
                logger.exception("Failed to download model from S3 URI '%s': %s", s3_uri, str(e))
                raise

    if not found:
        explicit = os.environ.get("MODEL_FILE_PATH")
        if explicit and os.path.exists(explicit):
            found = explicit

    if not found:
        logger.error("Model artifact not found in: %s. Provide MODEL_S3_URI or ensure model.tar.gz extracted with model.joblib.", candidates)
        raise FileNotFoundError("Model artifact not found and no MODEL_S3_URI provided.")

    try:
        logger.info("Loading model from: %s", found)
        _model = joblib.load(found)
        logger.info("Model loaded successfully.")
        return _model
    except Exception as e:
        logger.exception("Exception while loading model from %s: %s", found, str(e))
        raise RuntimeError(f"Failed to load model (joblib.load) from {found}: {e}")

# -------------------------
# Input / predict / output
# -------------------------
def input_fn(serialized_input, content_type="application/json"):
    if content_type in ("application/json", "application/jsonlines"):
        data = json.loads(serialized_input)
        if isinstance(data, dict):
            return [data]
        elif isinstance(data, list):
            return data
        else:
            raise ValueError("JSON input must be an object or array.")
    else:
        raise ValueError("Unsupported content type: %s" % content_type)

def predict_fn(input_data, model):
    rows = [flatten_ticket(t) for t in input_data]
    df = pd.DataFrame(rows)

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

    for tcol in ("subject", "resolution_text", "priority", "impact", "urgency", "category", "subcategory", "technician_name"):
        if tcol in X.columns:
            X[tcol] = X[tcol].fillna("").astype(str)

    for ncol in ("followers_count", "worklogTimespent", "created_hour", "created_weekday", "subject_len", "resolution_len", "has_followers"):
        if ncol in X.columns:
            X[ncol] = pd.to_numeric(X[ncol], errors="coerce").fillna(0.0)

    try:
        preds = model.predict(X)
    except Exception as e:
        logger.exception("Error during model.predict: %s", e)
        raise

    probs = None
    try:
        if hasattr(model, "predict_proba"):
            p = model.predict_proba(X)
            if p.ndim == 1:
                probs = p.tolist()
            else:
                probs = p[:, 1].tolist() if p.shape[1] > 1 else p[:, 0].tolist()
    except Exception as e:
        logger.warning("predict_proba not available or failed: %s", e)
        probs = None

    results = []
    for i, original in enumerate(input_data):
        res = {"ticketId": original.get("ticketId"), "prediction": int(preds[i])}
        if probs is not None:
            try:
                res["probability_class1"] = float(probs[i])
            except Exception:
                res["probability_class1"] = None
        results.append(res)
    return results

def output_fn(prediction, accept="application/json"):
    if accept == "application/json":
        return json.dumps(prediction), "application/json"
    raise ValueError("Unsupported accept type: %s" % accept)
