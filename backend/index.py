#!/usr/bin/env python3
"""
Strands agent that:
 - Uses Amazon Bedrock as the model (via strands.models.BedrockModel)
 - Uses a custom OpenSearch (Serverless) tool to retrieve similar tickets from your index
 - If OPENSEARCH_HOST is an OpenSearch Serverless collection ARN, the script will resolve
   the collection endpoint automatically using the opensearchserverless boto3 client.

Enhancements:
 - Optional vector (embedding) retrieval with Bedrock embeddings.
 - Caching for embeddings and recent queries (in-memory).
 - Short, contextual retrieval summaries are passed to the model prompt so the model
   needs less token-budget and provides more consistent structured output.
 - Improved search_tickets: hybrid vector + lexical scoring, query expansion (synonyms),
   fuzziness, phrase boosting, recency & closed-ticket boosting, and matched_fields returned.
"""

import json
import os
import re
import time
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse
from functools import lru_cache
from datetime import datetime, timedelta

import boto3
import botocore
from requests_aws4auth import AWS4Auth
from opensearchpy import OpenSearch, RequestsHttpConnection

from strands import Agent, tool
from strands.models import BedrockModel

# -----------------------
# Configuration (edit / env)
# -----------------------
OPENSEARCH_HOST = os.environ.get(
    "OPENSEARCH_HOST",
    "arn:aws:aoss:us-east-1:058264280347:collection/e67mqwgyf9a2476feaui"
)
OPENSEARCH_PORT = int(os.environ.get("OPENSEARCH_PORT", 443))
OPENSEARCH_INDEX = os.environ.get("OPENSEARCH_INDEX", "bedrock-knowledge-base-default-index")
AWS_REGION = os.environ.get("AWS_REGION", None)  # may be inferred from ARN if not provided
OPENSEARCH_SERVICE = os.environ.get("OPENSEARCH_SERVICE", None)
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")

# Controls
USE_VECTOR_SEARCH = os.environ.get("USE_VECTOR_SEARCH", "").strip().lower()
DEFAULT_VECTOR_ENABLED = bool(os.environ.get("BEDROCK_EMBEDDING_MODEL", os.environ.get("BEDROCK_MODEL_ID")))
if USE_VECTOR_SEARCH in ("1", "true", "yes"):
    USE_VECTOR_SEARCH_FLAG = True
elif USE_VECTOR_SEARCH in ("0", "false", "no"):
    USE_VECTOR_SEARCH_FLAG = False
else:
    USE_VECTOR_SEARCH_FLAG = DEFAULT_VECTOR_ENABLED

BEDROCK_EMBEDDING_MODEL = os.environ.get("BEDROCK_EMBEDDING_MODEL", "amazon.titan-embed-text-v2:0")

# Limits
EMBEDDING_MAX_CHARS = int(os.environ.get("EMBEDDING_MAX_CHARS", 2000))
RETRIEVAL_SUMMARY_STEPS = int(os.environ.get("RETRIEVAL_SUMMARY_STEPS", 3))
RETRIEVAL_SUMMARY_MAX_TOKENS = int(os.environ.get("RETRIEVAL_SUMMARY_MAX_TOKENS", 1500))  # heuristic hard limit

# Optional tuning
OPENSEARCH_SERVERLESS_ENV = os.environ.get("OPENSEARCH_SERVERLESS", "").strip().lower()

# -----------------------
# Helpers: ARN resolution and OpenSearch client (same approach as your indexing script)
# -----------------------
def is_arn(value: str) -> bool:
    return isinstance(value, str) and value.startswith("arn:")

def resolve_serverless_collection_endpoint_from_arn(collection_arn: str, region_hint: Optional[str] = None) -> Tuple[str, str]:
    arn_parts = collection_arn.split(":")
    if len(arn_parts) < 6:
        raise RuntimeError(f"Invalid ARN: {collection_arn}")
    arn_region = arn_parts[3] or None
    resource = arn_parts[5]
    resource_parts = resource.split("/")
    if len(resource_parts) != 2 or resource_parts[0] != "collection":
        raise RuntimeError(f"ARN does not appear to be a collection ARN: {collection_arn}")
    collection_id = resource_parts[1]
    region = region_hint or arn_region
    if not region:
        raise RuntimeError("Region could not be determined from ARN or AWS_REGION.")
    client = boto3.client("opensearchserverless", region_name=region)
    resp = client.batch_get_collection(ids=[collection_id])
    details = resp.get("collectionDetails", [])
    if not details:
        raise RuntimeError(f"No collection details returned for id {collection_id}. Response: {resp}")
    endpoint = details[0].get("collectionEndpoint")
    if not endpoint:
        raise RuntimeError(f"Collection returned but no collectionEndpoint found: {details[0]}")
    parsed = urlparse(endpoint)
    if parsed.netloc:
        host = parsed.netloc
    else:
        host = re.sub(r"^https?://", "", endpoint).rstrip("/")
    return host, region

def resolve_opensearch_host_and_service(host_value: str,
                                        env_region: Optional[str] = None,
                                        env_service: Optional[str] = None) -> Tuple[str, str, str]:
    if is_arn(host_value):
        host, inferred_region = resolve_serverless_collection_endpoint_from_arn(host_value, region_hint=env_region)
        service = "aoss"
        region = env_region or inferred_region
        return host, service, region
    else:
        parsed = urlparse(host_value)
        host = parsed.netloc if parsed.netloc else host_value
        service = env_service or ("aoss" if ".aoss." in host.lower() else "es")
        region = env_region or AWS_REGION or boto3.Session().region_name
        return host, service, region

# Resolve
resolved_host, resolved_service, resolved_region = resolve_opensearch_host_and_service(
    OPENSEARCH_HOST, env_region=AWS_REGION, env_service=OPENSEARCH_SERVICE
)
OPENSEARCH_HOST = resolved_host
OPENSEARCH_SERVICE = resolved_service
if not AWS_REGION and resolved_region:
    AWS_REGION = resolved_region

# serverless detection override
if OPENSEARCH_SERVERLESS_ENV in ("1", "true", "yes"):
    USE_OPENSEARCH_SERVERLESS = True
elif OPENSEARCH_SERVERLESS_ENV in ("0", "false", "no"):
    USE_OPENSEARCH_SERVERLESS = False
else:
    USE_OPENSEARCH_SERVERLESS = (OPENSEARCH_SERVICE == "aoss") or (".aoss." in (OPENSEARCH_HOST or "").lower()) or is_arn(os.environ.get("OPENSEARCH_HOST", ""))

print(f"[info] OpenSearch host={OPENSEARCH_HOST} service={OPENSEARCH_SERVICE} region={AWS_REGION} serverless={USE_OPENSEARCH_SERVERLESS} vector_search={USE_VECTOR_SEARCH_FLAG}")

def create_opensearch_client(region: str = AWS_REGION,
                             service: Optional[str] = OPENSEARCH_SERVICE,
                             host: str = OPENSEARCH_HOST,
                             port: int = OPENSEARCH_PORT) -> OpenSearch:
    session = boto3.Session(region_name=region)
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials found. Configure environment variables, profile, or IAM role.")
    frozen = credentials.get_frozen_credentials()
    service_name = service or ("aoss" if USE_OPENSEARCH_SERVERLESS else "es")
    if USE_OPENSEARCH_SERVERLESS:
        service_name = "aoss"
    awsauth = AWS4Auth(frozen.access_key,
                       frozen.secret_key,
                       region,
                       service_name,
                       session_token=frozen.token)
    client = OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30
    )
    return client

opensearch_client = create_opensearch_client()

# -----------------------
# Embedding helper (robust, returns None on failure) + tiny cache
# -----------------------
_embedding_cache: Dict[str, Optional[Tuple[float, ...]]] = {}

def get_bedrock_embedding(text: str,
                          model_id: str = BEDROCK_EMBEDDING_MODEL,
                          region: str = AWS_REGION,
                          max_input_chars: int = EMBEDDING_MAX_CHARS,
                          retry_attempts: int = 3,
                          backoff: float = 1.0) -> Optional[List[float]]:
    if not model_id:
        return None
    if not text:
        return None
    key = f"{model_id}::{text[:max_input_chars]}"
    if key in _embedding_cache:
        cached = _embedding_cache[key]
        return list(cached) if cached is not None else None

    if len(text) > max_input_chars:
        text = text[:max_input_chars]

    client = boto3.client("bedrock-runtime", region_name=region)

    if "titan-embed" in (model_id or "").lower() or "titan_embed" in (model_id or "").lower():
        payload = {"inputText": text}
    else:
        payload = {"input": text}
    body = json.dumps(payload)
    last_err = None
    for attempt in range(1, retry_attempts + 1):
        try:
            resp = client.invoke_model(modelId=model_id, body=body)
            b = resp.get("body")
            if hasattr(b, "read"):
                body_text = b.read().decode("utf-8")
            else:
                body_text = b
            parsed = None
            try:
                parsed = json.loads(body_text)
            except Exception:
                parsed = body_text

            if isinstance(parsed, dict):
                if "embedding" in parsed and isinstance(parsed["embedding"], list):
                    vec = [float(x) for x in parsed["embedding"]]
                    _embedding_cache[key] = tuple(vec)
                    return vec
                if "embeddings" in parsed and isinstance(parsed["embeddings"], list) and parsed["embeddings"]:
                    vec = [float(x) for x in parsed["embeddings"][0]]
                    _embedding_cache[key] = tuple(vec)
                    return vec
                if "results" in parsed and parsed["results"]:
                    r0 = parsed["results"][0]
                    if isinstance(r0, dict) and "embedding" in r0:
                        vec = [float(x) for x in r0["embedding"]]
                        _embedding_cache[key] = tuple(vec)
                        return vec
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], list):
                vec = [float(x) for x in parsed[0]]
                _embedding_cache[key] = tuple(vec)
                return vec

            last_err = RuntimeError(f"No embedding in response: {parsed}")
        except botocore.exceptions.ClientError as e:
            last_err = e
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "") or ""
            if code.lower().startswith("validation"):
                print(f"[warn] Bedrock validation error: {e}. payload len={len(body)}")
                _embedding_cache[key] = None
                return None
        except (botocore.exceptions.EndpointConnectionError,
                botocore.exceptions.ReadTimeoutError,
                botocore.exceptions.SSLError,
                botocore.exceptions.ConnectionError) as e:
            last_err = e
        except Exception as e:
            last_err = e

        if attempt < retry_attempts:
            sleep = backoff * (2 ** (attempt - 1))
            time.sleep(sleep)

    print(f"[warn] embedding failed after {retry_attempts} attempts. last_error={last_err}")
    _embedding_cache[key] = None
    return None

# -----------------------
# Query expansion utils
# -----------------------
_STOPWORDS = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "by", "and", "or", "is", "are", "with", "from"
}

_SYNONYMS = {
    "email": ["mail", "outlook", "exchange", "imap", "smtp"],
    "password": ["passwd", "pwd", "credentials", "login"],
    "printer": ["printing", "print"],
    "vpn": ["virtual private network"],
    "wifi": ["wi-fi", "wireless", "wireless network"],
    "slow": ["lag", "sluggish", "unresponsive", "slowdown"]
}

def _tokenize_and_expand(text: str, max_terms: int = 8) -> List[str]:
    """
    Very simple tokenizer + stopword removal + basic synonyms expansion.
    Returns top N tokens and synonyms appended to the list for use in multi_match queries.
    """
    if not text:
        return []
    # lower, remove punctuation but keep hyphens/periods within tokens
    cleaned = re.sub(r"[^\w\-\.\@]", " ", text.lower())
    tokens = [t for t in cleaned.split() if t and t not in _STOPWORDS]
    # preserve order and uniqueness
    seen = set()
    out = []
    for t in tokens:
        if t not in seen:
            out.append(t)
            seen.add(t)
        if len(out) >= max_terms:
            break
    # add synonyms for top tokens
    syns = []
    for t in out[:max_terms]:
        for k, vals in _SYNONYMS.items():
            if t == k or t.startswith(k):
                for v in vals:
                    if v not in seen:
                        syns.append(v)
                        seen.add(v)
                        if len(syns) >= 4:
                            break
            if len(syns) >= 4:
                break
        if len(syns) >= 4:
            break
    return out + syns

# -----------------------
# Utility: shorten retrieval summaries to include in prompt
# -----------------------
def summarize_for_prompt(hit_src: Dict[str, Any], max_steps: int = RETRIEVAL_SUMMARY_STEPS) -> str:
    subj = hit_src.get("subject") or ""
    steps = hit_src.get("resolutionSteps") or []
    steps_text = " | ".join([s.strip() for s in steps[:max_steps]])
    if steps_text:
        return f"{subj} -> {steps_text}"
    return subj

# -----------------------
# Tool: search_tickets (with improved hybrid search)
# -----------------------
_SEARCH_CACHE: Dict[Tuple[str, int, bool], Dict[str, Any]] = {}

@tool(name="search_tickets",
      description="Search the ticket knowledge base (OpenSearch) for similar tickets. "
                  "Returns top matching tickets including their displayId, subject, resolutionSteps and matched fields.")
def search_tickets(query_text: str, top_k: int = 3) -> Dict[str, Any]:
    """
    Hybrid retrieval:
      1) If vector search enabled and embeddings available -> try vector kNN retrieval.
      2) Combine vector hits with lexical BM25 signals via a bool query (should clauses).
      3) Fallback to classic multi_match if needed.

    Returns:
      {"results": [ {score, ticketId, displayId, subject, requester, technician, status, priority, resolutionSteps, matched_fields}, ... ] }
    """
    key = (query_text.strip(), int(top_k), bool(USE_VECTOR_SEARCH_FLAG))
    if key in _SEARCH_CACHE:
        return _SEARCH_CACHE[key]

    results: List[Dict[str, Any]] = []
    normalized_query = query_text.strip()
    expanded_terms = _tokenize_and_expand(normalized_query, max_terms=8)

    # Helper to extract concise result with matched fields (if highlight present)
    def _format_hit(h: Dict[str, Any]) -> Dict[str, Any]:
        src = h.get("_source", {})
        matched_fields = []
        # Look for highlight info if present
        high = h.get("highlight") or {}
        for f, fragments in high.items():
            if fragments:
                matched_fields.append(f)
        return {
            "score": h.get("_score"),
            "ticketId": src.get("ticketId"),
            "displayId": src.get("displayId"),
            "subject": src.get("subject"),
            "requester": src.get("requester"),
            "technician": src.get("technician"),
            "status": src.get("status"),
            "priority": src.get("priority"),
            "resolutionSteps": src.get("resolutionSteps", []),
            "matched_fields": matched_fields
        }

    # 1) Try vector + lexical hybrid retrieval when embedding available
    if USE_VECTOR_SEARCH_FLAG and BEDROCK_EMBEDDING_MODEL:
        emb = None
        try:
            emb = get_bedrock_embedding(normalized_query, model_id=BEDROCK_EMBEDDING_MODEL)
        except Exception:
            emb = None

        if emb:
            # Build hybrid query: prefer knn but also include strong lexical signals.
            # First, attempt AOSS knn (preferred). If that returns hits, return them directly.
            knn_body = {
                "size": top_k,
                "query": {
                    "knn": {
                        "field": "embedding",
                        "query_vector": emb,
                        "k": top_k,
                        "num_candidates": max(128, top_k * 64)
                    }
                },
                "_source": ["ticketId", "displayId", "subject", "requester", "technician", "resolutionSteps", "status", "priority"]
            }
            try:
                resp = opensearch_client.search(body=knn_body, index=OPENSEARCH_INDEX)
                hits = resp.get("hits", {}).get("hits", [])
                if hits:
                    # format results and return (semantic nearest neighbors)
                    for h in hits:
                        results.append(_format_hit(h))
                    _SEARCH_CACHE[key] = {"results": results}
                    return {"results": results}
            except Exception:
                # Knn may fail (plugin/syntax mismatch), continue to hybrid approach
                pass

            # Hybrid bool query: combine vector score (via script_score if vector native isn't available)
            # If your OpenSearch supports script_score with cosine or dot product you could add it; here we
            # create a strong should clause hierarchy: subject phrase, multi_match fuzz, resolutionSteps match.
            should_clauses = []

            # high-precision phrase match on subject (boosted)
            if normalized_query:
                should_clauses.append({
                    "match_phrase": {"subject": {"query": normalized_query, "boost": 6.0}}
                })
                # also a fuzzy short match on subject
                should_clauses.append({
                    "match": {"subject": {"query": normalized_query, "fuzziness": "AUTO", "boost": 2.5}}
                })

            # expanded term multi_match across fields
            if expanded_terms:
                combined_expanded = " ".join(expanded_terms)
                should_clauses.append({
                    "multi_match": {
                        "query": combined_expanded,
                        "fields": [
                            "subject^3",
                            "subcategory^2",
                            "requester_name^1",
                            "technician_name^1",
                            "resolutionSteps^1.25"
                        ],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                        "operator": "or",
                        "boost": 1.5
                    }
                })

            # aspects: join direct tokens as term clauses to boost exact field matches
            for term in expanded_terms[:4]:
                should_clauses.append({"match": {"resolutionSteps": {"query": term, "boost": 1.2}}})

            # Boost closed tickets (historical successes) and more recent tickets
            # We model this with `function_score` combining the boolean shoulds with weight/decay functions.
            current_time = datetime.utcnow()
            # recency decay: use updatedTime field (assumes ISO date strings stored in index)
            function_score_query = {
                "function_score": {
                    "query": {"bool": {"should": should_clauses, "minimum_should_match": 1}},
                    "boost_mode": "sum",
                    "score_mode": "sum",
                    "functions": [
                        # boosting closed tickets
                        {
                            "filter": {"term": {"status.keyword": "Closed"}},
                            "weight": 1.5
                        },
                        # recency: documents updated in last 30 days get a small boost
                        {
                            "filter": {
                                "range": {"updatedTime": {"gte": (current_time - timedelta(days=30)).isoformat()}}
                            },
                            "weight": 1.2
                        }
                    ]
                }
            }

            hybrid_body = {
                "size": top_k,
                "query": {
                    # wrap function_score so BM25 signals can dominate but semantic vector can still be used if supported
                    "bool": {
                        "should": [
                            function_score_query,
                            # fallback multi_match to ensure lexical coverage
                            {
                                "multi_match": {
                                    "query": combined_expanded if expanded_terms else normalized_query,
                                    "fields": ["subject^3", "resolutionSteps^1.5", "subcategory^2", "requester_name", "technician_name"],
                                    "type": "best_fields",
                                    "fuzziness": "AUTO",
                                    "operator": "or"
                                }
                            }
                        ]
                    }
                },
                "_source": ["ticketId", "displayId", "subject", "requester", "technician", "resolutionSteps", "status", "priority"],
                "highlight": {"fields": {"subject": {}, "resolutionSteps": {}, "subcategory": {}}}
            }

            try:
                resp = opensearch_client.search(body=hybrid_body, index=OPENSEARCH_INDEX)
                hits = resp.get("hits", {}).get("hits", [])
                for h in hits:
                    results.append(_format_hit(h))
                if results:
                    _SEARCH_CACHE[key] = {"results": results}
                    return {"results": results}
            except Exception as e:
                # hybrid failed - continue to lexical fallback
                print(f"[warn] hybrid retrieval failed: {e}")

    # 2) Classic multi_match fallback (robust)
    # Build a strong lexical query: subject phrase + multi_match fuzzy + resolution step boosting
    strong_should = []
    if normalized_query:
        strong_should.append({"match_phrase": {"subject": {"query": normalized_query, "boost": 5.0}}})
        strong_should.append({"match": {"subject": {"query": normalized_query, "fuzziness": "AUTO", "boost": 2.0}}})

    if expanded_terms:
        strong_should.append({
            "multi_match": {
                "query": " ".join(expanded_terms),
                "fields": ["subject^3", "subcategory^2", "resolutionSteps^1.5"],
                "type": "best_fields",
                "fuzziness": "AUTO",
                "operator": "or",
                "boost": 1.5
            }
        })

    # ensure we always have something to query
    lexical_body = {
        "size": top_k,
        "query": {
            "bool": {
                "should": strong_should if strong_should else [{"match_all": {}}],
                "minimum_should_match": 1 if strong_should else 0
            }
        },
        "_source": ["ticketId", "displayId", "subject", "requester", "technician", "resolutionSteps", "status", "priority"],
        "highlight": {"fields": {"subject": {}, "resolutionSteps": {}, "subcategory": {}}}
    }

    try:
        resp = opensearch_client.search(body=lexical_body, index=OPENSEARCH_INDEX)
        hits = resp.get("hits", {}).get("hits", [])
        for h in hits:
            results.append(_format_hit(h))
    except Exception as e:
        print(f"[error] OpenSearch lexical search failed: {e}")

    _SEARCH_CACHE[key] = {"results": results}
    return {"results": results}

# -----------------------
# Small synthesizer (same as before)
# -----------------------
def synthesize_steps_from_retrievals(retrievals: List[Dict[str, Any]], max_steps: int = 8) -> List[str]:
    seen = {}
    order = []
    for r in retrievals:
        for step in r.get("resolutionSteps", []) or []:
            normalized = step.strip()
            if normalized not in seen:
                seen[normalized] = 0
                order.append(normalized)
            seen[normalized] += 1
    ordered = sorted(order, key=lambda s: (-seen[s], order.index(s)))
    return ordered[:max_steps]

# -----------------------
# Create Bedrock model and agent with improved system prompt (few-shot + context slot)
# -----------------------
bedrock_model = BedrockModel(
    model_id=BEDROCK_MODEL_ID,
    temperature=0.0,    # deterministic
    max_tokens=512,
    region_name=AWS_REGION
)

EXAMPLE_OUTPUT = {
    "recommendedSteps": [
        {"step": "Reset user password via admin console", "supportingDisplayIds": ["123"], "notes": "User must confirm MFA."}
    ],
    "sources": [
        {"displayId": "123", "subject": "Password reset for user", "resolutionSteps": ["Reset password", "Confirm MFA"]}
    ]
}

SYSTEM_PROMPT = (
    "You are an IT support assistant. Given a new ticket and a short list of similar historical tickets, "
    "produce an ordered JSON object with: `recommendedSteps` (ordered list of objects with keys: step, supportingDisplayIds, notes) "
    "and `sources` (the matching tickets used). Be concise and only include necessary steps. "
    "Example output (compact):\n" + json.dumps(EXAMPLE_OUTPUT) + "\n"
)

agent = Agent(
    model=bedrock_model,
    tools=[search_tickets],
    system_prompt=SYSTEM_PROMPT,
)

# -----------------------
# Function to generate resolution suggestions for a new ticket dictionary
# -----------------------
def build_retrieval_context(retrievals: List[Dict[str, Any]], max_chars: int = RETRIEVAL_SUMMARY_MAX_TOKENS) -> str:
    parts = []
    for r in retrievals:
        summary = summarize_for_prompt(r, max_steps=RETRIEVAL_SUMMARY_STEPS)
        if summary:
            parts.append(f"- [{r.get('displayId')}] {summary}")
    combined = "\n".join(parts)
    if len(combined) > max_chars:
        combined = combined[:max_chars].rsplit("\n", 1)[0]
    return combined

def suggest_resolution_for_ticket(new_ticket: Dict[str, Any], top_k: int = 3) -> Dict[str, Any]:
    query_text = f"{new_ticket.get('subject','')}. Requester: {new_ticket.get('requester',{}).get('name','')}. Subcategory: {new_ticket.get('subcategory','')}. Priority: {new_ticket.get('priority','')}."
    retrieval_resp = search_tickets(query_text, top_k=top_k)
    retrievals = retrieval_resp.get("results", []) if retrieval_resp else []

    retrieval_summary = build_retrieval_context(retrievals, max_chars=RETRIEVAL_SUMMARY_MAX_TOKENS)

    instruction = (
        f"New ticket:\n{json.dumps({k: new_ticket.get(k) for k in ['displayId','subject','requester','subcategory','priority','description']}, default=str, indent=0)}\n\n"
        f"Context - similar past tickets (top {len(retrievals)}):\n{retrieval_summary or '(no similar tickets found)'}\n\n"
        "Using the context and your IT knowledge, provide a concise ordered list of recommended resolution steps. "
        "For each step include: `step` (short text), `supportingDisplayIds` (list of displayId strings from the context that support the step), and `notes` (any prerequisites or checks). "
        "Return only valid JSON with keys `recommendedSteps` and `sources` (sources should be the retrieved tickets full objects)."
    )

    response = agent(instruction)
    out_text = str(response)
    parsed = None
    try:
        start = out_text.find("{")
        end = out_text.rfind("}") + 1
        if start != -1 and end != -1 and end > start:
            candidate = out_text[start:end]
            parsed = json.loads(candidate)
    except Exception:
        parsed = None

    if parsed is None:
        synthesized = synthesize_steps_from_retrievals(retrievals)
        recommended = []
        for s in synthesized:
            supporting = [r["displayId"] for r in retrievals if s in (r.get("resolutionSteps") or [])]
            recommended.append({
                "step": s,
                "supportingDisplayIds": supporting,
                "notes": ""
            })
        parsed = {
            "recommendedSteps": recommended,
            "sources": retrievals
        }

    return parsed

# -----------------------
# Example usage
# -----------------------
if __name__ == "__main__":
    new_ticket_example = {
        "displayId": "NEW-001",
        "subject": "Can't access company email from laptop",
        "requester": {"name": "Jim Halpert"},
        "subcategory": "Access",
        "priority": "High",
        "description": "User reports that they cannot sign into company email on their laptop after password change."
    }

    suggestion = suggest_resolution_for_ticket(new_ticket_example, top_k=4)
    print(json.dumps(suggestion, indent=2, default=str))
