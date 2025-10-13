#!/usr/bin/env python3
"""
train_and_test_escalation.py

Improved training + single-ticket test harness.

Requirements:
  pip install boto3 pandas scikit-learn joblib xgboost (optional)

Usage:
  python train_and_test_escalation.py
"""

import os
import json
import io
import math
import boto3
import joblib
import random
from typing import List, Dict, Any
from datetime import datetime
import numpy as np
import pandas as pd

# sklearn imports
import sklearn
from sklearn.model_selection import train_test_split, RandomizedSearchCV, StratifiedKFold
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler, FunctionTransformer
from sklearn.impute import SimpleImputer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.base import BaseEstimator, TransformerMixin

# Optional: XGBoost (use if installed)
try:
    import xgboost as xgb  # type: ignore
    XGBOOST_AVAILABLE = True
except Exception:
    XGBOOST_AVAILABLE = False

# ---------- CONFIG ----------
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET = "fixella-bucket-superhack"            # <-- set this if you want upload to S3
S3_KEY = "it_tickets_kb.json"
MODEL_S3_PATH = "models/ticket_escalation_model.joblib"
LOCAL_MODEL_PATH = "ticket_escalation_model.joblib"

s3 = boto3.client("s3", region_name=AWS_REGION)

# ---------- Helpers ----------
def load_json_from_s3(bucket: str, key: str) -> List[dict]:
    resp = s3.get_object(Bucket=bucket, Key=key)
    body = resp["Body"].read()
    data = json.loads(body.decode("utf-8"))
    if isinstance(data, dict):
        return [data]
    return data

def safe_fromiso(ts: str):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        # try a couple of fallbacks
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(ts, fmt)
            except Exception:
                pass
    return None

def flatten_ticket(ticket: dict) -> dict:
    """
    Flatten ticket dict into a feature dict. NOTE: we intentionally DO NOT use techgroup_name
    as an input feature (so missing techGroup in test tickets is fine).
    """
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
    # NOTE: techgroup intentionally NOT included among features
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
    # numeric
    try:
        flat["worklogTimespent"] = float(ticket.get("worklogTimespent") or 0.0)
    except Exception:
        flat["worklogTimespent"] = 0.0
    # followers
    flat["followers_count"] = len(ticket.get("followers") or [])
    # timestamps
    created = safe_fromiso(ticket.get("createdTime"))
    updated = safe_fromiso(ticket.get("updatedTime"))
    flat["createdTime"] = created
    flat["updatedTime"] = updated
    flat["created_hour"] = created.hour if created else -1
    flat["created_weekday"] = created.weekday() if created else -1
    # derived text features
    flat["subject_len"] = len(flat["subject"])
    flat["resolution_len"] = len(flat["resolution_text"])
    flat["has_followers"] = int(flat["followers_count"] > 0)
    # combined text for TF-IDF experiments (we'll use subject and resolution separately)
    return flat

def label_escalation(flat_ticket: dict, escalation_marker: str = "escalation") -> int:
    """
    Use the original labeling heuristic for training: techGroup.name contains 'escalation'.
    This function expects the *original* flattened dict that includes techgroup_name.
    But since our flattened training rows above do not include techgroup_name,
    we'll accept raw ticket dict in training load step to label, or if given flattened dict
    without techgroup we fallback to conservative label 0.
    """
    # fallback: label 0 if no techgroup info available
    tg = None
    # some training paths may pass raw ticket (with 'techGroup')
    if "techgroup_name" in flat_ticket:
        tg = flat_ticket.get("techgroup_name")
    else:
        # no techgroup available -> default label 0
        tg = ""
    if tg is None:
        tg = ""
    return int(escalation_marker.lower() in str(tg).lower())

# ---------- Custom Transformers ----------
class TextSelector(BaseEstimator, TransformerMixin):
    """Select a text column and optionally return as-is (for TfidfVectorizer in pipeline)."""
    def __init__(self, key):
        self.key = key
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        return X[self.key].fillna("").astype(str).values

class ColumnSelector(BaseEstimator, TransformerMixin):
    """Select columns and return a numpy array or DataFrame for downstream transformers."""
    def __init__(self, keys):
        self.keys = keys
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        return X[self.keys]

# ---------- Data preparation ----------
def prepare_dataframe_from_raw_tickets(raw_tickets: List[dict]) -> pd.DataFrame:
    """
    Accept the raw JSON ticket objects. We use the techGroup in this step only to create
    the label; the model's input features WILL NOT include techGroup.
    """
    # produce flattened rows (but need techgroup_name for label checking if present)
    rows = []
    for t in raw_tickets:
        r = flatten_ticket(t)
        # extract techgroup_name if present into r for labeling then drop in features
        r_raw_tg = (t.get("techGroup") or {}).get("name") if t and isinstance(t, dict) else None
        r["techgroup_name"] = r_raw_tg
        rows.append(r)
    df = pd.DataFrame(rows)
    # label using techgroup_name presence
    df["escalated"] = df.apply(lambda r: label_escalation(r), axis=1)
    # fill missing categorical values
    df["priority"] = df["priority"].fillna("Unknown")
    df["impact"] = df["impact"].fillna("Unknown")
    df["urgency"] = df["urgency"].fillna("Unknown")
    df["category"] = df["category"].fillna("Unknown")
    df["subcategory"] = df["subcategory"].fillna("Unknown")
    df["technician_name"] = df["technician_name"].fillna("Unknown")
    # drop techgroup_name from actual features to force model to learn from content
    # keep it only for analysis if needed
    return df

# ---------- Build pipeline ----------
def build_pipeline(sklearn_version=sklearn.__version__):
    # OneHotEncoder compatibility
    try:
        from packaging import version as _ver
        modern = _ver.parse(sklearn_version) >= _ver.parse("1.2")
    except Exception:
        parts = sklearn_version.split(".")
        major = int(parts[0]) if parts and parts[0].isdigit() else 0
        minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        modern = (major, minor) >= (1, 2)

    if modern:
        ohe_kwargs = {"handle_unknown": "ignore", "sparse_output": False}
    else:
        ohe_kwargs = {"handle_unknown": "ignore", "sparse": False}

    # text pipelines: subject and resolution_text separately (helps models learn differences)
    subject_tfidf = Pipeline([
        ("selector", TextSelector("subject")),
        ("tfidf", TfidfVectorizer(max_features=3000, ngram_range=(1,2), stop_words="english"))
    ])
    resolution_tfidf = Pipeline([
        ("selector", TextSelector("resolution_text")),
        ("tfidf", TfidfVectorizer(max_features=3000, ngram_range=(1,2), stop_words="english"))
    ])

    # categorical pipeline
    cat_cols = ["priority", "impact", "urgency", "category", "subcategory", "technician_name"]
    cat_pipeline = Pipeline([
        ("selector", ColumnSelector(cat_cols)),
        ("imputer", SimpleImputer(strategy="constant", fill_value="Unknown")),
        ("onehot", OneHotEncoder(**ohe_kwargs))
    ])

    # numeric pipeline
    num_cols = ["followers_count", "worklogTimespent", "created_hour", "created_weekday", "subject_len", "resolution_len", "has_followers"]
    num_pipeline = Pipeline([
        ("selector", ColumnSelector(num_cols)),
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler())
    ])

    # Combine features using ColumnTransformer-like behavior
    # We'll use FeatureUnion of named pipelines but easier to use ColumnTransformer directly:
    from sklearn.compose import ColumnTransformer
    preprocessor = ColumnTransformer(transformers=[
        ("subject_tfidf", subject_tfidf, ["subject"]),        # ColumnTransformer accepts list for column spec
        ("resolution_tfidf", resolution_tfidf, ["resolution_text"]),
        ("cat", cat_pipeline, cat_cols),
        ("num", num_pipeline, num_cols)
    ], remainder="drop", sparse_threshold=0)

    # # classifier: RandomForest (robust) or XGBoost if available
    # if XGBOOST_AVAILABLE:
    #     clf = xgb.XGBClassifier(use_label_encoder=False, eval_metric="logloss", n_jobs=4, random_state=42)
    # else:
    clf = RandomForestClassifier(n_estimators=300, n_jobs=-1, random_state=42, class_weight="balanced")

    pipeline = Pipeline([
        ("preproc", preprocessor),
        ("clf", clf)
    ])
    return pipeline

# ---------- Training + evaluation ----------
def build_and_train(df: pd.DataFrame, run_hpo: bool = False):
    # features
    feature_cols = ["subject", "resolution_text", "priority", "impact", "urgency", "category", "subcategory", "technician_name",
                    "followers_count", "worklogTimespent", "created_hour", "created_weekday", "subject_len", "resolution_len", "has_followers"]
    X = df[feature_cols]
    y = df["escalated"].astype(int)

    # small check: need at least 2 classes for training
    if y.nunique() < 2:
        raise ValueError("Training labels contain only one class. Need both classes for training.")

    X_train, X_test, y_train, y_test = train_test_split(X, y, stratify=y, test_size=0.2, random_state=42)

    pipeline = build_pipeline()

    if run_hpo:
        # cheap RandomizedSearch over a few params (adjust as desired)
        param_dist = {}
        if XGBOOST_AVAILABLE:
            param_dist = {
                "clf__n_estimators": [50, 100, 200],
                "clf__max_depth": [3, 6, 10],
                "clf__learning_rate": [0.01, 0.1, 0.2],
            }
        else:
            param_dist = {
                "clf__n_estimators": [100, 200, 300],
                "clf__max_features": ["sqrt", 0.3, 0.5],
                "clf__max_depth": [None, 10, 30],
            }
        search = RandomizedSearchCV(pipeline, param_distributions=param_dist, n_iter=6, cv=3, verbose=2, n_jobs=1, random_state=42)
        search.fit(X_train, y_train)
        best = search.best_estimator_
        print("Best HPO params:", search.best_params_)
        model = best
    else:
        pipeline.fit(X_train, y_train)
        model = pipeline

    # evaluation
    y_pred = model.predict(X_test)
    print("Classification report (test set):")
    print(classification_report(y_test, y_pred, digits=4))
    try:
        if hasattr(model, "predict_proba"):
            prob = model.predict_proba(X_test)[:,1]
            print("ROC AUC:", roc_auc_score(y_test, prob))
    except Exception:
        print("ROC AUC unavailable.")

    # Save model locally and upload to S3
    
    joblib.dump(model, LOCAL_MODEL_PATH)
    print(f"Model saved locally to {LOCAL_MODEL_PATH}")
    try:
        s3.upload_file(LOCAL_MODEL_PATH, S3_BUCKET, MODEL_S3_PATH)
        print(f"Model uploaded to s3://{S3_BUCKET}/{MODEL_S3_PATH}")
    except Exception as e:
        print("Warning: failed to upload model to S3:", e)

    return model

# ---------- Single-ticket inference helper ----------
def prepare_single_ticket_df(ticket: dict) -> pd.DataFrame:
    """
    Create a dataframe for a single ticket that matches training features. Accepts tickets
    that do NOT include 'techGroup'.
    """
    flat = flatten_ticket(ticket)
    # ensure categorical fills exactly as training
    flat["priority"] = flat.get("priority") or "Unknown"
    flat["impact"] = flat.get("impact") or "Unknown"
    flat["urgency"] = flat.get("urgency") or "Unknown"
    flat["category"] = flat.get("category") or "Unknown"
    flat["subcategory"] = flat.get("subcategory") or "Unknown"
    flat["technician_name"] = flat.get("technician_name") or "Unknown"

    # ensure numeric fields exist
    for c in ["followers_count", "worklogTimespent", "created_hour", "created_weekday", "subject_len", "resolution_len", "has_followers"]:
        if c not in flat:
            flat[c] = 0
    # DataFrame
    df = pd.DataFrame([flat])
    return df

def predict_single_ticket(model, ticket: dict):
    df = prepare_single_ticket_df(ticket)
    feature_cols = ["subject", "resolution_text", "priority", "impact", "urgency", "category", "subcategory", "technician_name",
                    "followers_count", "worklogTimespent", "created_hour", "created_weekday", "subject_len", "resolution_len", "has_followers"]
    X = df[feature_cols]
    pred = model.predict(X)[0]
    try:
        prob = model.predict_proba(X)[0]
        prob1 = float(prob[1]) if len(prob) > 1 else None
    except Exception:
        prob1 = None
    return {"prediction": int(pred), "probability_class1": prob1, "input_features": X.to_dict(orient="records")[0]}

# ---------- Example usage ----------
def main_train_and_test(run_hpo=False):
    print("Loading JSON from S3...")
    raw = load_json_from_s3(S3_BUCKET, S3_KEY)
    df = prepare_dataframe_from_raw_tickets(raw)
    print(f"Loaded {len(df)} tickets")
    print(df[["ticketId", "subject", "techgroup_name", "escalated"]].head(10))
    model = build_and_train(df, run_hpo=run_hpo)
    print("Training complete.")

    # Hardcoded example ticket WITHOUT techGroup (per your requirement)
    example_ticket = {
        "ticketId": "SINGLE-TEST-1",
        "displayId": "X",
        "subject": "Printer is not printing urgent quarterly reports",
        # no techGroup provided
        "technician": {"name": "Unknown"},
        "priority": "High",
        "impact": "High",
        "urgency": "High",
        "category": "Network",
        "subcategory": "Printer",
        "followers": [],
        "resolutionSteps": [],
        "createdTime": "2025-10-08T18:30:13.091535",
        "worklogTimespent": "0.00",
        "resolutionViolated": False
    }

    result = predict_single_ticket(model, example_ticket)
    print("\nSingle-ticket prediction (example without techGroup):")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    # set run_hpo=True to run the randomized hyperparameter search (slower)
    main_train_and_test(run_hpo=False)
