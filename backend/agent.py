#!/usr/bin/env python3
"""
Strands agent that:
 - Uses Amazon Bedrock as the model (via strands.models.BedrockModel)
 - Uses a custom OpenSearch (Serverless) tool to retrieve similar tickets from your index
 - If OPENSEARCH_HOST is an OpenSearch Serverless collection ARN, the script will resolve
   the collection endpoint automatically using the opensearchserverless boto3 client.
"""

import json
import os
import re
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse

import boto3
from requests_aws4auth import AWS4Auth
from opensearchpy import OpenSearch, RequestsHttpConnection

from strands import Agent, tool
from strands.models import BedrockModel

# -----------------------
# Configuration (edit / env)
# -----------------------
# You may put an OpenSearch Serverless collection ARN here (example you gave),
# or the actual collection endpoint host (like "07tjusf2h91cunochc.us-east-1.aoss.amazonaws.com")
OPENSEARCH_HOST = os.environ.get(
    "OPENSEARCH_HOST",
    "arn:aws:aoss:us-east-1:058264280347:collection/e67mqwgyf9a2476feaui"
)
OPENSEARCH_PORT = int(os.environ.get("OPENSEARCH_PORT", 443))
OPENSEARCH_INDEX = os.environ.get("OPENSEARCH_INDEX", "bedrock-knowledge-base-default-index")
AWS_REGION = os.environ.get("AWS_REGION", None)  # may be inferred from ARN if not provided
# For OpenSearch Serverless use "aoss", for managed domains use "es".
# If you pass an ARN the code will set this to "aoss" automatically.
OPENSEARCH_SERVICE = os.environ.get("OPENSEARCH_SERVICE", None)
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
# Optional override to force serverless behavior (useful in CI): "1/true/yes" or "0/false/no"
OPENSEARCH_SERVERLESS_ENV = os.environ.get("OPENSEARCH_SERVERLESS", "").strip().lower()
# -----------------------


def is_arn(value: str) -> bool:
    return isinstance(value, str) and value.startswith("arn:")


def resolve_serverless_collection_endpoint_from_arn(collection_arn: str, region_hint: Optional[str] = None) -> Tuple[str, str]:
    """
    Given a collection ARN like:
      arn:aws:aoss:ap-south-1:058264280347:collection/r4qeef5zh6n0lngse3h9
    call opensearchserverless.batch_get_collection(ids=[id]) to retrieve the collectionEndpoint.
    Returns (host, region) where host is the host portion (no https://), or raises RuntimeError.
    """
    arn_parts = collection_arn.split(":")
    if len(arn_parts) < 6:
        raise RuntimeError(f"Invalid ARN: {collection_arn}")

    arn_region = arn_parts[3] or None
    resource = arn_parts[5]  # e.g., "collection/<id>"
    resource_parts = resource.split("/")
    if len(resource_parts) != 2 or resource_parts[0] != "collection":
        raise RuntimeError(f"ARN does not appear to be a collection ARN: {collection_arn}")
    collection_id = resource_parts[1]

    region = region_hint or arn_region
    if not region:
        raise RuntimeError("Region could not be determined from ARN or AWS_REGION.")

    # call opensearchserverless to fetch collection details (collectionEndpoint)
    client = boto3.client("opensearchserverless", region_name=region)
    resp = client.batch_get_collection(ids=[collection_id])
    details = resp.get("collectionDetails", [])
    if not details:
        raise RuntimeError(f"No collection details returned for id {collection_id}. Response: {resp}")

    endpoint = details[0].get("collectionEndpoint")
    if not endpoint:
        raise RuntimeError(f"Collection returned but no collectionEndpoint found: {details[0]}")

    # strip scheme if present
    parsed = urlparse(endpoint)
    if parsed.netloc:
        host = parsed.netloc
    else:
        host = re.sub(r"^https?://", "", endpoint).rstrip("/")
    return host, region


def resolve_opensearch_host_and_service(host_value: str,
                                        env_region: Optional[str] = None,
                                        env_service: Optional[str] = None) -> Tuple[str, str, str]:
    """
    If host_value is an ARN -> resolve to collectionEndpoint and set service='aoss' and region from ARN (unless env_region provided).
    Otherwise treat host_value as a hostname (possibly with https://) and set service to env_service or default 'es'.
    Returns tuple (host, service, region)
    """
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


# Resolve host/service/region and override globals if needed
resolved_host, resolved_service, resolved_region = resolve_opensearch_host_and_service(
    OPENSEARCH_HOST, env_region=AWS_REGION, env_service=OPENSEARCH_SERVICE
)
OPENSEARCH_HOST = resolved_host
OPENSEARCH_SERVICE = resolved_service
if not AWS_REGION and resolved_region:
    AWS_REGION = resolved_region

# Determine whether to operate in AOSS (serverless) mode.
if OPENSEARCH_SERVERLESS_ENV in ("1", "true", "yes"):
    USE_OPENSEARCH_SERVERLESS = True
elif OPENSEARCH_SERVERLESS_ENV in ("0", "false", "no"):
    USE_OPENSEARCH_SERVERLESS = False
else:
    # If service resolved to 'aoss' or host contains .aoss. or original was ARN, assume serverless.
    USE_OPENSEARCH_SERVERLESS = (OPENSEARCH_SERVICE == "aoss") or (".aoss." in (OPENSEARCH_HOST or "").lower()) or is_arn(os.environ.get("OPENSEARCH_HOST", ""))

print(f"[info] using OpenSearch host: {OPENSEARCH_HOST}  (service={OPENSEARCH_SERVICE}, region={AWS_REGION}, serverless={USE_OPENSEARCH_SERVERLESS})")


def create_opensearch_client(region: str = AWS_REGION,
                             service: Optional[str] = OPENSEARCH_SERVICE,
                             host: str = OPENSEARCH_HOST,
                             port: int = OPENSEARCH_PORT) -> OpenSearch:
    """
    Create a SigV4-signed OpenSearch client using requests-aws4auth.
    Works for Amazon OpenSearch Service (service='es') and OpenSearch Serverless (service='aoss').
    The client will sign requests using 'aoss' when serverless is in use.
    """
    session = boto3.Session(region_name=region)
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials found. Configure environment variables, profile, or IAM role.")
    frozen = credentials.get_frozen_credentials()

    # prefer explicit service parameter, otherwise derive from serverless flag
    service_name = service or ("aoss" if USE_OPENSEARCH_SERVERLESS else "es")
    # if serverless detection says True, force 'aoss' to ensure correct SigV4 service name
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


# Create client once
opensearch_client = create_opensearch_client()

# -----------------------
# Tool: search_tickets
# -----------------------
@tool(name="search_tickets",
      description="Search the ticket knowledge base (OpenSearch) for similar tickets. "
                  "Returns top matching tickets including their displayId, subject, and resolutionSteps.")
def search_tickets(query_text: str, top_k: int = 3) -> Dict[str, Any]:
    """
    Query OpenSearch for tickets similar to query_text.
    Returns a JSON-serializable dict with hits.
    Args:
        query_text: Natural language text describing the new ticket
        top_k: how many results to return
    """
    # Multi-field text search (adjust fields to match your index mapping)
    body = {
        "size": top_k,
        "query": {
            "multi_match": {
                "query": query_text,
                "fields": [
                    "subject^3",
                    "subcategory^2",
                    "requester.name",
                    "technician.name",
                    "resolutionSteps",
                    "subject.ngram",  # if you indexed ngram fields
                ],
                "type": "best_fields",
                "operator": "or"
            }
        },
        # return full source so we can access resolutionSteps
        "_source": ["ticketId", "displayId", "subject", "requester", "technician", "resolutionSteps", "status", "priority"]
    }

    # For diagnostics, optionally print the query (comment out in production)
    # print(f"[debug] OpenSearch query body: {json.dumps(body)}")

    resp = opensearch_client.search(body=body, index=OPENSEARCH_INDEX)
    hits = resp.get("hits", {}).get("hits", [])

    results = []
    for h in hits:
        src = h.get("_source", {})
        results.append({
            "score": h.get("_score"),
            "ticketId": src.get("ticketId"),
            "displayId": src.get("displayId"),
            "subject": src.get("subject"),
            "requester": src.get("requester"),
            "technician": src.get("technician"),
            "status": src.get("status"),
            "priority": src.get("priority"),
            "resolutionSteps": src.get("resolutionSteps", [])
        })

    return {"results": results}


# -----------------------
# Helper: small synthesizer (optional)
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
# Create Bedrock model and agent
# -----------------------
bedrock_model = BedrockModel(
    model_id=BEDROCK_MODEL_ID,
    temperature=0.0,
    max_tokens=1024,
    region_name=AWS_REGION
)

agent = Agent(
    model=bedrock_model,
    tools=[search_tickets],
    system_prompt=(
        "You are an IT support agent whose job is to produce clear, step-by-step resolution "
        "instructions for new incident tickets. When appropriate, search the ticket knowledge base using "
        "the search_tickets tool, retrieve similar closed/resolved tickets, and synthesize a concise set "
        "of resolution steps. For each step, indicate (if present) which historical ticket(s) support it "
        "by displayId. The resolution step should not include any such suggestions of contacting the IT team."
    ),
)

# -----------------------
# Function to generate resolution suggestions for a new ticket dictionary
# -----------------------
def suggest_resolution_for_ticket(new_ticket: Dict[str, Any], top_k: int = 3) -> Dict[str, Any]:
    query_text = f"{new_ticket.get('subject','')}. " \
                 f"Requester: {new_ticket.get('requester',{}).get('name','')}. " \
                 f"Subcategory: {new_ticket.get('subcategory','')}. " \
                 f"Priority: {new_ticket.get('priority','')}."

    instruction = (
        f"New ticket (JSON):\n{json.dumps(new_ticket, default=str)}\n\n"
        "First, use the `search_tickets` tool with the following query to find up to "
        f"{top_k} similar past tickets: ```{query_text}```\n\n"
        "Then synthesize a recommended ordered list of resolution steps for this ticket. "
        "For each step, include: (1) concise step text, (2) which historical ticket displayId(s) support it, "
        "and (3) any important notes (e.g., prerequisites). Provide the final answer as JSON with keys: "
        "`recommendedSteps` (ordered list of objects with step, supportingDisplayIds, notes) and `sources` (list of matched tickets)."
    )

    response = agent(instruction)
    out_text = str(response)
    parsed = None
    try:
        start = out_text.find("{")
        end = out_text.rfind("}") + 1
        if start != -1 and end != -1 and end > start:
            parsed = json.loads(out_text[start:end])
    except Exception:
        parsed = None

    if parsed is None:
        retrievals = search_tickets(query_text, top_k=top_k).get("results", [])
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
