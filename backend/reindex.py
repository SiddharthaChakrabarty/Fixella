#!/usr/bin/env python3
"""
reindex_tickets.py - robust Bedrock embedding + OpenSearch indexing

Main fixes in this version:
 - Automatic detection of OpenSearch Serverless (AOSS) via OPENSEARCH_SERVERLESS env or OPENSEARCH_HOST containing ".aoss."
 - When serverless:
     * Do NOT supply explicit _id in bulk actions (AOSS rejects document id on create/index bulk operations).
     * Do NOT use refresh="wait_for" (AOSS rejects wait_for refresh policy).
     * Skip explicit indices.refresh at the end.
 - When NOT serverless:
     * Include explicit _id in bulk actions and keep refresh="wait_for" semantics.
 - Helpers.bulk success counts are taken from the method return value where available.
 - Keeps robust Bedrock embedding helper (returns None on failure so bulk continues).
"""

import os
import json
import time
from typing import List, Dict, Any, Optional
from uuid import uuid4

import boto3
import botocore
from requests_aws4auth import AWS4Auth
from opensearchpy import OpenSearch, RequestsHttpConnection, helpers
from tqdm import tqdm

# -------------------------
# Configuration from env
# -------------------------
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "v5imukfrs3r1k6oi37dk.us-east-2.aoss.amazonaws.com")
OPENSEARCH_PORT = int(os.environ.get("OPENSEARCH_PORT", 443))
OPENSEARCH_INDEX = os.environ.get("OPENSEARCH_INDEX", "bedrock-knowledge-base-default-index")
S3_BUCKET = os.environ.get("S3_BUCKET", "fixella-ai-bucket")
S3_KEY = os.environ.get("S3_KEY", "it_tickets_kb.json")
# e.g. "amazon.titan-embed-text-v2:0" or set empty to skip embeddings
BEDROCK_EMBEDDING_MODEL = os.environ.get("BEDROCK_EMBEDDING_MODEL", "amazon.titan-embed-text-v2:0")
BULK_CHUNK = int(os.environ.get("BULK_CHUNK", 100))

# Safety / limits
BEDROCK_MAX_INPUT_CHARS = int(os.environ.get("BEDROCK_MAX_INPUT_CHARS", 2000))  # trim input to this size
BEDROCK_RETRY_ATTEMPTS = int(os.environ.get("BEDROCK_RETRY_ATTEMPTS", 3))
BEDROCK_RETRY_BACKOFF = float(os.environ.get("BEDROCK_RETRY_BACKOFF", 1.0))  # seconds base

# Detect serverless / AOSS usage:
# - If OPENSEARCH_SERVERLESS env var is set to true/1/yes -> serverless
# - Else, autodetect if the host contains ".aoss." which is typical for AOSS endpoints
_env_serverless = os.environ.get("OPENSEARCH_SERVERLESS", "").strip().lower()
if _env_serverless in ("1", "true", "yes"):
    USE_OPENSEARCH_SERVERLESS = True
elif _env_serverless in ("0", "false", "no"):
    USE_OPENSEARCH_SERVERLESS = False
else:
    USE_OPENSEARCH_SERVERLESS = (".aoss." in (OPENSEARCH_HOST or "").lower())

print(f"[info] OPENSEARCH_SERVERLESS={USE_OPENSEARCH_SERVERLESS}")

if not OPENSEARCH_HOST or not S3_BUCKET or not S3_KEY:
    raise RuntimeError("Set OPENSEARCH_HOST, S3_BUCKET and S3_KEY environment variables before running")

# -------------------------
# Helpers: OpenSearch client
# -------------------------
def create_opensearch_client(region: str = AWS_REGION, host: str = OPENSEARCH_HOST, port: int = OPENSEARCH_PORT):
    session = boto3.Session(region_name=region)
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials found. Configure env vars, profile, or IAM role.")
    frozen = credentials.get_frozen_credentials()
    # service "aoss" is correct for Amazon OpenSearch Serverless endpoints (or leave as "es" for classic OpenSearch)
    service_name = "aoss" if USE_OPENSEARCH_SERVERLESS else "es"
    awsauth = AWS4Auth(frozen.access_key, frozen.secret_key, region, service_name, session_token=frozen.token)
    client = OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=60
    )
    return client

opensearch_client = create_opensearch_client()

# -------------------------
# Robust Bedrock embedding helper
# -------------------------
def get_bedrock_embedding(text: str,
                          model_id: str = BEDROCK_EMBEDDING_MODEL,
                          region: str = AWS_REGION,
                          max_input_chars: int = BEDROCK_MAX_INPUT_CHARS,
                          retry_attempts: int = BEDROCK_RETRY_ATTEMPTS,
                          backoff: float = BEDROCK_RETRY_BACKOFF) -> Optional[List[float]]:
    """
    Call Bedrock embedding model to get a vector.
    Returns list[float] on success, or None on failure (non-fatal).
    """
    if not model_id:
        return None

    # guard input length
    if len(text) > max_input_chars:
        text = text[:max_input_chars]

    client = boto3.client("bedrock-runtime", region_name=region)

    # Prepare model-native payload for known Titan embed models
    native_payload = None
    if "titan-embed" in (model_id or "").lower() or "titan_embed" in (model_id or "").lower():
        native_payload = {"inputText": text}
    else:
        native_payload = {"input": text}

    request_body = json.dumps(native_payload)

    last_err = None
    for attempt in range(1, retry_attempts + 1):
        try:
            resp = client.invoke_model(modelId=model_id, body=request_body)
            body = resp.get("body")
            if hasattr(body, "read"):
                body_text = body.read().decode("utf-8")
            else:
                body_text = body

            parsed = None
            try:
                parsed = json.loads(body_text)
            except Exception:
                parsed = body_text

            # Parse likely shapes (Titan examples show top-level "embedding")
            if isinstance(parsed, dict):
                if "embedding" in parsed and isinstance(parsed["embedding"], list):
                    return [float(x) for x in parsed["embedding"]]
                if "embeddings" in parsed and isinstance(parsed["embeddings"], list) and parsed["embeddings"]:
                    return [float(x) for x in parsed["embeddings"][0]]
                if "results" in parsed and parsed["results"]:
                    r0 = parsed["results"][0]
                    if isinstance(r0, dict) and "embedding" in r0:
                        return [float(x) for x in r0["embedding"]]
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], list):
                return [float(x) for x in parsed[0]]

            last_err = RuntimeError(f"Could not find embedding in model response: {parsed}")
        except botocore.exceptions.ClientError as e:
            last_err = e
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "") or ""
            if code.lower().startswith("validation"):
                print(f"[warn] Bedrock validation error: {e}. Payload sent: {native_payload}")
                return None
        except (botocore.exceptions.EndpointConnectionError,
                botocore.exceptions.ConnectionClosedError,
                botocore.exceptions.ReadTimeoutError,
                botocore.exceptions.SSLError,
                botocore.exceptions.ConnectionError) as e:
            last_err = e
        except Exception as e:
            last_err = e

        if attempt < retry_attempts:
            sleep = backoff * (2 ** (attempt - 1))
            print(f"[info] get_bedrock_embedding attempt {attempt} failed, retrying after {sleep:.1f}s ...")
            time.sleep(sleep)

    print(f"[warn] get_bedrock_embedding failed after {retry_attempts} attempts. Last error: {last_err}")
    return None


# -------------------------
# Create index mapping (structured)
# -------------------------
def create_structured_index(index_name: str,
                            client: OpenSearch,
                            embedding_dim: Optional[int] = None):
    # If index exists, skip creation (or delete+recreate if desired)
    if client.indices.exists(index=index_name):
        print(f"[info] Index '{index_name}' already exists. Skipping creation.")
        return

    mapping = {
        "settings": {
            "index": {"knn": True}
        },
        "mappings": {
            "dynamic_templates": [
                {
                    "strings": {
                        "match_mapping_type": "string",
                        "mapping": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 2147483647}}}
                    }
                }
            ],
            "properties": {
                "ticketId": {"type": "keyword"},
                "displayId": {"type": "keyword"},
                "subject": {"type": "text"},
                "requester_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "technician_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "priority": {"type": "keyword"},
                "status": {"type": "keyword"},
                "createdTime": {"type": "date"},
                "updatedTime": {"type": "date"},
                "resolutionSteps": {"type": "text"},
            }
        }
    }

    if embedding_dim:
        mapping["mappings"]["properties"]["embedding"] = {
            "type": "knn_vector",
            "dimension": embedding_dim,
            "space_type": "l2",
            "method": {
                "name": "hnsw",
                "engine": "faiss",
                "parameters": {}
            }
        }

    print(f"[info] Creating index '{index_name}' with mapping (embedding_dim={embedding_dim})...")
    client.indices.create(index=index_name, body=mapping)
    print("[info] Index created.")


# -------------------------
# Load S3 JSON
# -------------------------
def load_s3_json(bucket: str = S3_BUCKET, key: str = S3_KEY) -> List[Dict[str, Any]]:
    s3 = boto3.client("s3", region_name=AWS_REGION)
    print(f"[info] Downloading s3://{bucket}/{key} ...")
    obj = s3.get_object(Bucket=bucket, Key=key)
    raw = obj["Body"].read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise RuntimeError("Expected a JSON array of ticket objects in the S3 file")
    print(f"[info] Loaded {len(data)} ticket objects from S3")
    return data


# -------------------------
# Convert ticket to structured doc
# -------------------------
def structure_ticket(ticket: Dict[str, Any]) -> Dict[str, Any]:
    requester_name = ticket.get("requester", {}).get("name") if isinstance(ticket.get("requester"), dict) else None
    technician_name = ticket.get("technician", {}).get("name") if isinstance(ticket.get("technician"), dict) else None
    return {
        "ticketId": ticket.get("ticketId"),
        "displayId": ticket.get("displayId"),
        "subject": ticket.get("subject"),
        "requester_name": requester_name,
        "technician_name": technician_name,
        "priority": ticket.get("priority"),
        "status": ticket.get("status"),
        "createdTime": ticket.get("createdTime"),
        "updatedTime": ticket.get("updatedTime"),
        "resolutionSteps": [str(s).strip() for s in (ticket.get("resolutionSteps") or [])],
        "_source_raw": ticket
    }


# -------------------------
# Bulk index
# -------------------------
def bulk_index_tickets(tickets: List[Dict[str, Any]],
                       index_name: str,
                       client: OpenSearch,
                       compute_embeddings: bool = True,
                       embedding_model: Optional[str] = BEDROCK_EMBEDDING_MODEL,
                       mapping_dim: Optional[int] = None,
                       chunk_size: int = BULK_CHUNK):
    total = len(tickets)
    print(f"[info] Preparing to index {total} tickets to index '{index_name}' (chunk size {chunk_size}). Embeddings: {bool(embedding_model)}")
    actions = []
    succeeded = 0
    failed = 0

    for t in tqdm(tickets, desc="tickets"):
        doc = structure_ticket(t)
        embedding_vector = None

        if compute_embeddings and embedding_model:
            try:
                # choose text to embed: subject + first 2 resolution steps
                embed_text = (doc.get("subject") or "") + " " + " ".join((doc.get("resolutionSteps")[:2] if doc.get("resolutionSteps") else []))
                if len(embed_text.strip()) < 5:
                    embed_text = json.dumps(doc.get("_source_raw", {}))
                embedding_vector = get_bedrock_embedding(embed_text, model_id=embedding_model)
            except Exception as e:
                print(f"[warn] unexpected embedding error for ticket {doc.get('displayId') or doc.get('ticketId')}: {e}")
                embedding_vector = None

        body = {k: v for k, v in doc.items() if k != "_source_raw"}

        if embedding_vector:
            if mapping_dim is None:
                mapping_dim = len(embedding_vector)
            vec = [float(x) for x in embedding_vector]
            if len(vec) > mapping_dim:
                vec = vec[:mapping_dim]
            elif len(vec) < mapping_dim:
                vec = vec + [0.0] * (mapping_dim - len(vec))
            body["embedding"] = vec

        # safe doc id
        if doc.get("ticketId"):
            doc_id = str(doc.get("ticketId"))
        elif doc.get("displayId"):
            doc_id = str(doc.get("displayId"))
        else:
            doc_id = str(uuid4())

        action = {
            "_op_type": "index",
            "_index": index_name,
            "_source": body
        }
        # Only include explicit _id when not serverless (serverless rejects explicit ID in create/index bulk)
        if not USE_OPENSEARCH_SERVERLESS:
            action["_id"] = doc_id

        actions.append(action)

        if len(actions) >= chunk_size:
            try:
                if USE_OPENSEARCH_SERVERLESS:
                    success_count, errors = helpers.bulk(client, actions)
                else:
                    # non-serverless: use wait_for behavior
                    success_count, errors = helpers.bulk(client, actions, refresh="wait_for")
                # helpers.bulk returns (success_count, errors)
                succeeded += int(success_count or 0)
                # errors may be a list or number depending on client; attempt best-effort accounting
                if isinstance(errors, list) and errors:
                    # errors is a list of item-level errors
                    failed += len(errors)
            except Exception as e:
                print(f"[error] bulk chunk failed: {e}")
                # conservative: treat whole chunk as failed
                failed += len(actions)
            actions = []

    # flush remaining actions
    if actions:
        try:
            if USE_OPENSEARCH_SERVERLESS:
                success_count, errors = helpers.bulk(client, actions)
            else:
                success_count, errors = helpers.bulk(client, actions, refresh="wait_for")
            succeeded += int(success_count or 0)
            if isinstance(errors, list) and errors:
                failed += len(errors)
        except Exception as e:
            print(f"[error] final bulk chunk failed: {e}")
            failed += len(actions)

    print(f"[info] Bulk indexing complete. Succeeded: {succeeded}, Failed: {failed}")
    return {"succeeded": succeeded, "failed": failed}


# -------------------------
# Run flow
# -------------------------
def run_reindex():
    # 1) load S3 JSON first
    tickets = load_s3_json(S3_BUCKET, S3_KEY)
    if not tickets:
        print("[info] No tickets found, exiting.")
        return

    # If embeddings are enabled, compute a sample embedding to discover dimension before creating the index.
    sample_embedding_dim = None
    if BEDROCK_EMBEDDING_MODEL:
        print("[info] Embedding model configured, attempting to get sample embedding to infer dimension...")
        sample_ticket = tickets[0]
        sample_doc = structure_ticket(sample_ticket)
        sample_text = (sample_doc.get("subject") or "") + " " + " ".join((sample_doc.get("resolutionSteps")[:2] or []))
        if len(sample_text.strip()) < 5:
            sample_text = json.dumps(sample_doc.get("_source_raw", {}))
        try:
            emb = get_bedrock_embedding(sample_text, model_id=BEDROCK_EMBEDDING_MODEL)
            if emb:
                sample_embedding_dim = len(emb)
                print(f"[info] Sample embedding obtained. Dimension = {sample_embedding_dim}")
            else:
                print("[warn] Sample embedding could not be obtained; falling back to default dim 1024")
                sample_embedding_dim = 1024
        except Exception as e:
            print(f"[warn] Could not obtain sample embedding due to exception: {e}. Falling back to default dimension 1024.")
            sample_embedding_dim = 1024

    # 2) create index with discovered dimension (or without embedding field)
    create_structured_index(OPENSEARCH_INDEX, opensearch_client, embedding_dim=sample_embedding_dim)

    # 3) bulk index
    results = bulk_index_tickets(tickets,
                                index_name=OPENSEARCH_INDEX,
                                client=opensearch_client,
                                compute_embeddings=bool(BEDROCK_EMBEDDING_MODEL),
                                embedding_model=BEDROCK_EMBEDDING_MODEL,
                                mapping_dim=sample_embedding_dim,
                                chunk_size=BULK_CHUNK)

    # 4) final index refresh (only for non-serverless)
    if not USE_OPENSEARCH_SERVERLESS:
        try:
            opensearch_client.indices.refresh(index=OPENSEARCH_INDEX)
        except Exception:
            pass
    else:
        print("[info] Skipping explicit index refresh for serverless OpenSearch (AOSS).")

    print("[done] reindex finished:", results)


if __name__ == "__main__":
    run_reindex()
