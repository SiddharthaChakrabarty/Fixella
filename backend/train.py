# train.py
import os
import json
from typing import List
import pandas as pd
import joblib
from datetime import datetime

# sklearn imports
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score

# ---------- Helper functions (same as your local script) ----------
def flatten_ticket(ticket: dict) -> dict:
    flat = {}
    flat["ticketId"] = ticket.get("ticketId")
    flat["displayId"] = ticket.get("displayId")
    flat["subject"] = ticket.get("subject", "")
    flat["techgroup_name"] = (ticket.get("techGroup") or {}).get("name")
    flat["technician_name"] = (ticket.get("technician") or {}).get("name")
    flat["priority"] = ticket.get("priority")
    flat["impact"] = ticket.get("impact")
    flat["urgency"] = ticket.get("urgency")
    flat["category"] = ticket.get("category")
    flat["subcategory"] = ticket.get("subcategory")
    flat["resolutionViolated"] = bool(ticket.get("resolutionViolated"))
    try:
        flat["worklogTimespent"] = float(ticket.get("worklogTimespent") or 0.0)
    except Exception:
        flat["worklogTimespent"] = 0.0
    flat["followers_count"] = len(ticket.get("followers") or [])
    flat["resolution_text"] = " ".join(ticket.get("resolutionSteps") or [])
    # simple ISO parse
    def parse_ts(ts):
        try:
            return datetime.fromisoformat(ts) if ts else None
        except Exception:
            return None
    created = parse_ts(ticket.get("createdTime"))
    flat["created_hour"] = created.hour if created else -1
    flat["created_weekday"] = created.weekday() if created else -1
    bigtext = " ".join(filter(None, [
        flat["subject"],
        flat["resolution_text"],
        flat["category"] or "",
        flat["subcategory"] or "",
        flat["techgroup_name"] or ""
    ]))
    flat["text"] = bigtext
    return flat

def label_escalation(flat_ticket: dict, escalation_marker: str = "escalation") -> int:
    tg = (flat_ticket.get("techgroup_name") or "").lower()
    return int(escalation_marker.lower() in tg)

def prepare_dataframe(json_list: List[dict]) -> pd.DataFrame:
    rows = [flatten_ticket(t) for t in json_list]
    df = pd.DataFrame(rows)
    df["escalated"] = df.apply(lambda r: label_escalation(r), axis=1)
    df["priority"] = df["priority"].fillna("Unknown")
    df["category"] = df["category"].fillna("Unknown")
    df["subcategory"] = df["subcategory"].fillna("Unknown")
    df["technician_name"] = df["technician_name"].fillna("Unknown")
    return df

# ---------- Training entry point ----------
if __name__ == "__main__":
    # SageMaker provides channels via env vars
    train_dir = os.environ.get("SM_CHANNEL_TRAIN", "/opt/ml/input/data/train")
    model_dir = os.environ.get("SM_MODEL_DIR", "/opt/ml/model")   # where to save artifact

    # Expect a single JSON file in train_dir (you will upload to S3 and pass it as channel)
    data_files = [os.path.join(train_dir, f) for f in os.listdir(train_dir) if f.endswith(".json")]
    if not data_files:
        raise SystemExit("No training JSON found in SM_CHANNEL_TRAIN: " + train_dir)

    # load JSON (assume it is an array)
    with open(data_files[0], "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if isinstance(raw, dict) and ("records" in raw or "tickets" in raw):
        raw = raw.get("records") or raw.get("tickets") or []
    if not isinstance(raw, list):
        raise SystemExit("Unexpected JSON structure; expected list of tickets.")

    df = prepare_dataframe(raw)

    # features
    text_col = "text"
    cat_cols = ["priority", "impact", "urgency", "category", "subcategory", "technician_name"]
    num_cols = ["followers_count", "worklogTimespent", "created_hour", "created_weekday", "resolutionViolated"]

    X = df[[text_col] + cat_cols + num_cols]
    y = df["escalated"].astype(int)

    # simple pipeline -- identical to your local script
    text_transformer = ("tfidf", TfidfVectorizer(max_features=5000, ngram_range=(1,2)), text_col)
    cat_pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value="Unknown")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False if hasattr(OneHotEncoder, 'sparse_output') else False))
    ])
    preprocessor = ColumnTransformer([
        ("text", Pipeline([("tfidf", TfidfVectorizer(max_features=5000, ngram_range=(1,2)))]), text_col),
        ("cat", cat_pipeline, cat_cols),
        ("num", Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]), num_cols)
    ], remainder="drop", sparse_threshold=0)

    clf = RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1, class_weight="balanced")
    pipeline = Pipeline([("preproc", preprocessor), ("clf", clf)])

    # train/test split for an evaluation in the training job
    X_train, X_test, y_train, y_test = train_test_split(X, y, stratify=y, test_size=0.2, random_state=42)
    pipeline.fit(X_train, y_train)

    # optional evaluation print (visible in CloudWatch logs)
    y_pred = pipeline.predict(X_test)
    try:
        prob = pipeline.predict_proba(X_test)[:,1]
        auc = roc_auc_score(y_test, prob)
    except Exception:
        auc = None
    print("Classification report:")
    print(classification_report(y_test, y_pred, digits=4))
    print("ROC AUC:", auc)

    # Save the pipeline to model_dir (SageMaker bundles this as model.tar.gz)
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, "model.joblib")
    joblib.dump(pipeline, model_path)
    print("Saved model to:", model_path)
