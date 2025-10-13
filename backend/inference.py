# inference.py
import os
import json
import joblib
import numpy as np
import pandas as pd
from datetime import datetime

# The training code used custom transformers (TextSelector, ColumnSelector).
# If your saved joblib references custom classes you used when training,
# ensure they are defined here with the exact same names or the model was saved
# using cloudpickle. If you used the shared-module approach, import those classes.
# For robustness include simple stand-ins below (must match names used when saving).

from sklearn.base import BaseEstimator, TransformerMixin

class TextSelector(BaseEstimator, TransformerMixin):
    def __init__(self, key):
        self.key = key
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        try:
            return X[self.key].fillna("").astype(str).values
        except Exception:
            return pd.Series([str(x.get(self.key, "")) for x in X]).values

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

# ----------------- feature helpers (must match training) -----------------
def parse_iso(ts):
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        formats = ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S")
        for fmt in formats:
            try:
                return datetime.strptime(ts, fmt)
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
    # fill defaults used during training
    flat["priority"] = flat.get("priority") or "Unknown"
    flat["impact"] = flat.get("impact") or "Unknown"
    flat["urgency"] = flat.get("urgency") or "Unknown"
    flat["category"] = flat.get("category") or "Unknown"
    flat["subcategory"] = flat.get("subcategory") or "Unknown"
    flat["technician_name"] = flat.get("technician_name") or "Unknown"
    return flat

# Model object will be stored in global variable `model`
model = None

def model_fn(model_dir):
    """
    Called by SageMaker to load the model. The training packaging created model.joblib at
    the root of the tarball, so the container will extract it under model_dir/model.joblib.
    """
    global model
    model_path = os.path.join(model_dir, "model.joblib")
    if not os.path.exists(model_path):
        # also check common alternative names
        alt = [os.path.join(model_dir, "model.pkl"), os.path.join(model_dir, "ticket_escalation_model.joblib")]
        for p in alt:
            if os.path.exists(p):
                model_path = p
                break
    model = joblib.load(model_path)
    return model

def input_fn(serialized_input, content_type):
    """
    Accepts application/json content. Input may be a single ticket (JSON object),
    or a list of tickets.
    """
    if content_type == "application/json" or content_type == "application/jsonlines":
        data = json.loads(serialized_input)
        # If user sends a single ticket object, wrap it in a list
        if isinstance(data, dict):
            return [data]
        elif isinstance(data, list):
            return data
        else:
            raise ValueError("Unsupported JSON input type: expected object or list")
    else:
        raise ValueError(f"Unsupported content type: {content_type}")

def predict_fn(input_data, model):
    """
    input_data is a list of raw ticket JSON dicts.
    Returns predictions and probabilities (if available).
    """
    # Flatten into dataframe using same features as training
    rows = [flatten_ticket(t) for t in input_data]
    df = pd.DataFrame(rows)
    feature_cols = [
        "subject", "resolution_text",
        "priority", "impact", "urgency", "category", "subcategory", "technician_name",
        "followers_count", "worklogTimespent", "created_hour", "created_weekday",
        "subject_len", "resolution_len", "has_followers"
    ]
    X = df[feature_cols]
    # ensure types align: fill missing columns
    for c in feature_cols:
        if c not in X.columns:
            X[c] = None

    preds = model.predict(X)
    # optionally include probabilities
    probs = None
    try:
        if hasattr(model, "predict_proba"):
            p = model.predict_proba(X)
            # p[:,1] is probability for class 1
            probs = p[:, 1].tolist()
    except Exception:
        probs = None

    results = []
    for i, ticket in enumerate(input_data):
        res = {
            "ticketId": ticket.get("ticketId"),
            "prediction": int(preds[i]),
        }
        if probs is not None:
            res["probability_class1"] = float(probs[i])
        results.append(res)
    return results

def output_fn(prediction, accept="application/json"):
    if accept == "application/json":
        return json.dumps(prediction), "application/json"
    raise ValueError("Only application/json is supported as accept header")
