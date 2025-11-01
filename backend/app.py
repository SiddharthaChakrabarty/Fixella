# app_server.py  (replace your existing large Flask file with this or merge changes)
from flask import Flask, request, jsonify
import boto3  # type: ignore
import bcrypt
import jwt  # type: ignore
import uuid
import datetime
from botocore.exceptions import ClientError  # type: ignore
from flask_cors import CORS  # type: ignore
from boto3.dynamodb.conditions import Key  # type: ignore
import requests  # type: ignore
import json
from sklearn.inspection import permutation_importance
import os
import joblib  # type: ignore
import tempfile
import sys
from sklearn.base import BaseEstimator, TransformerMixin
import logging

# === try to import the agent function if available ===
try:
    from agents.resolution_steps_agent import suggest_resolution_for_ticket  # optional
    AGENT_IMPORT_AVAILABLE = True
except Exception:
    AGENT_IMPORT_AVAILABLE = False

try:
    from agents.agent_substeps_llm import suggest_substeps_for_resolution_step
    AGENT_SUBSTEPS_AVAILABLE = True
except Exception:
    AGENT_SUBSTEPS_AVAILABLE = False

# chat agent import (used as fallback if master agent not available)
try:
    from agents.chat_agent import chat_with_agent
    CHAT_AGENT_AVAILABLE = True
except Exception:
    CHAT_AGENT_AVAILABLE = False

# KB store imports (unchanged)
from agents.kb_store import (
    kb_get_status,
    kb_get_tickets,
    kb_find_ticket,
    kb_search,
    kb_reload,
    kb_get_kg,
    kb_find_node,
    kb_find_edges,
    kb_search_nodes,
)

# Try to import master_agent and a selection of its tool wrappers (preferred)
MASTER_AVAILABLE = False
generate_substeps_tool = None
suggest_resolution_tool = None
chat_with_agent_tool = None
analyze_snapshot_tool = None
where_to_go_tool = None
search_similar_tickets_tool = None

try:
    import agents.master_agent as master_agent_module  # type: ignore

    MASTER_AVAILABLE = True
    # try to bind known tool wrapper functions if they exist
    generate_substeps_tool = getattr(master_agent_module, "generate_substeps_tool", None)
    suggest_resolution_tool = getattr(master_agent_module, "suggest_resolution_tool", None)
    chat_with_agent_tool = getattr(master_agent_module, "chat_with_agent_tool", None)
    analyze_snapshot_tool = getattr(master_agent_module, "analyze_snapshot_tool", None)
    where_to_go_tool = getattr(master_agent_module, "where_to_go_tool", None)
    search_similar_tickets_tool = getattr(master_agent_module, "search_similar_tickets_tool", None)
except Exception:
    MASTER_AVAILABLE = False

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app.config["JWT_SECRET"] = "hello123"
app.config["AWS_REGION"] = "us-east-2"
app.config["DYNAMO_TABLE"] = "FixellaUsers"
app.config["SAGEMAKER_ENDPOINT"] = "ticket-escalation-endpoint-4"  # replace with your endpoint or set via env/config

app.config["MODEL_S3_URI"] = "s3://fixella-ai-bucket/models/ticket_escalation_model.joblib"  # optional

dynamodb = boto3.resource("dynamodb", region_name=app.config["AWS_REGION"])
table = dynamodb.Table(app.config["DYNAMO_TABLE"])

class TextSelector(BaseEstimator, TransformerMixin):
    def __init__(self, key):
        self.key = key
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        try:
            # if X is a DataFrame
            series = X[self.key].fillna("").astype(str)
            return series.values
        except Exception:
            # fallback if X is list/dict-like
            try:
                return [str(x.get(self.key, "")) for x in X]
            except Exception:
                # last resort: return empty strings
                return ["" for _ in range(len(X))]

class ColumnSelector(BaseEstimator, TransformerMixin):
    def __init__(self, keys):
        self.keys = keys
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        try:
            return X[self.keys]
        except Exception:
            import pandas as pd
            return pd.DataFrame(X)[self.keys]

@app.route("/signup", methods=["POST"])
def signup():
    try:
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")
        name = data.get("name")

        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400

        # Check if user already exists
        response = table.scan(
            FilterExpression="email = :email",
            ExpressionAttributeValues={":email": email},
        )
        if response["Items"]:
            return jsonify({"error": "User already exists"}), 400

        # Hash password
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        # Create user record
        user = {
            "userId": str(uuid.uuid4()),
            "email": email,
            "name": name,
            "passwordHash": password_hash,
            "createdAt": datetime.datetime.utcnow().isoformat(),
        }
        table.put_item(Item=user)

        return jsonify({"message": "User registered successfully"}), 201

    except ClientError as e:
        return jsonify({"error": str(e)}), 500

@app.route("/login", methods=["POST"])
def login():
    try:
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400

        # Find user by email
        response = table.scan(
            FilterExpression="email = :email",
            ExpressionAttributeValues={":email": email},
        )
        if not response["Items"]:
            return jsonify({"error": "User not found"}), 404

        user = response["Items"][0]

        # Verify password
        if not bcrypt.checkpw(
            password.encode("utf-8"), user["passwordHash"].encode("utf-8")
        ):
            return jsonify({"error": "Invalid credentials"}), 401

        # Generate JWT token
        token = jwt.encode(
            {
                "userId": user["userId"],
                "email": user["email"],
                "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=6),
            },
            app.config["JWT_SECRET"],
            algorithm="HS256",
        )

        return jsonify({"message": "Login successful", "token": token}), 200

    except ClientError as e:
        return jsonify({"error": str(e)}), 500

@app.route("/me", methods=["GET"])
def get_profile():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Missing token"}), 401

    try:
        decoded = jwt.decode(token, app.config["JWT_SECRET"], algorithms=["HS256"])
        userId = decoded["userId"]

        response = table.get_item(Key={"userId": userId})
        if "Item" not in response:
            return jsonify({"error": "User not found"}), 404

        user = response["Item"]
        return (
            jsonify(
                {
                    "userId": user["userId"],
                    "email": user["email"],
                    "name": user.get("name"),
                }
            ),
            200,
        )

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401

@app.route("/tickets", methods=["GET"])
def get_tickets():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Missing token"}), 401

    try:
        decoded = jwt.decode(token, app.config["JWT_SECRET"], algorithms=["HS256"])
        userId = decoded["userId"]

        # DynamoDB table for tickets
        tickets_table = dynamodb.Table("FixellaTickets")

        # Query using the technician GSI
        response = tickets_table.query(
            IndexName="technician-index",  # GSI on top-level technician_userId
            KeyConditionExpression="technician_userId = :tid",
            ExpressionAttributeValues={":tid": userId},
        )

        tickets = response.get("Items", [])

        # Map tickets to a cleaner structure for frontend
        ticket_list = []
        for t in tickets:
            ticket_list.append(
                {
                    "ticketId": t.get("ticketId"),
                    "displayId": t.get("displayId"),
                    "title": t.get("subject"),
                    "ticketType": t.get("ticketType"),
                    "requestType": t.get("requestType"),
                    "source": t.get("source"),
                    "clientName": t.get("client", {}).get("name"),
                    "siteName": t.get("site", {}).get("name"),
                    "requesterName": t.get("requester", {}).get("name"),
                    "technicianName": t.get("technician", {}).get("name"),
                    "status": t.get("status"),
                    "priority": t.get("priority"),
                    "impact": t.get("impact"),
                    "urgency": t.get("urgency"),
                    "createdAt": t.get("createdTime"),
                    "updatedAt": t.get("updatedTime"),
                    "worklogTimespent": t.get("worklogTimespent", "0.00"),
                }
            )

        return jsonify({"tickets": ticket_list}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except ClientError as e:
        return jsonify({"error": str(e)}), 500

# === new route ===
@app.route("/ai/ask_ai", methods=["POST"])
def ask_ai():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Missing token"}), 401
    try:
        decoded = jwt.decode(token, app.config["JWT_SECRET"], algorithms=["HS256"])
        userId = decoded["userId"]
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401

    try:
        data = request.get_json() or {}
        # Accept either: {"ticketId": "..."} or full ticket JSON in "ticket"
        ticket_id = data.get("ticketId")
        ticket_payload = data.get("ticket")

        if ticket_id and not ticket_payload:
            # fetch ticket from FixellaTickets table
            tickets_table = dynamodb.Table("FixellaTickets")
            resp = tickets_table.get_item(Key={"ticketId": ticket_id})
            if "Item" not in resp:
                return jsonify({"error": "Ticket not found"}), 404
            ticket_payload = resp["Item"]

        if not ticket_payload:
            return jsonify({"error": "ticket or ticketId required"}), 400

        # Normalize minimal structure expected by agent
        new_ticket = {
            "displayId": ticket_payload.get("displayId")
            or ticket_payload.get("ticketId")
            or "NEW-UNKNOWN",
            "subject": ticket_payload.get("subject")
            or ticket_payload.get("title")
            or "",
            "requester": {
                "name": (ticket_payload.get("requester", {}) or {}).get("name")
                or ticket_payload.get("requesterName")
            },
            "subcategory": ticket_payload.get("subcategory")
            or ticket_payload.get("ticketType"),
            "priority": ticket_payload.get("priority"),
            "description": ticket_payload.get("description")
            or ticket_payload.get("body")
            or "",
        }

        # Option 1: call master_agent suggest_resolution tool if available
        if MASTER_AVAILABLE and suggest_resolution_tool is not None:
            try:
                ticket_json = json.dumps(new_ticket)
                tool_res = suggest_resolution_tool(ticket_json, top_k=4)
                if isinstance(tool_res, dict) and tool_res.get("ok"):
                    return jsonify({"ok": True, "source": "master_agent", "result": tool_res.get("result")}), 200
                else:
                    # fallback to using raw result or error if tool returned error
                    return jsonify({"ok": False, "source": "master_agent", "error": tool_res.get("error", "tool failed")}), 500
            except Exception as e:
                # fall through to other methods
                logger.exception("master_agent suggest_resolution_tool failed: %s", e)

        # Option 2: call in-process agent if available
        if AGENT_IMPORT_AVAILABLE:
            suggestion = suggest_resolution_for_ticket(new_ticket, top_k=4)
            return jsonify({"ok": True, "source": "import", "result": suggestion}), 200

        # Option 3: master_agent present but tool not registered -> ask master_agent to process request free-form
        if MASTER_AVAILABLE:
            try:
                # we use the master_agent's process_request helper if available
                process_request = getattr(master_agent_module, "process_request", None)
                if callable(process_request):
                    instruction = f"Suggest resolution steps for ticket:\n{json.dumps(new_ticket, default=str)}\nReturn JSON only."
                    resp = process_request(instruction)
                    return jsonify({"ok": True, "source": "master_agent.process_request", "result": resp.get("result")}), 200
            except Exception:
                logger.exception("master_agent.process_request fallback failed")

        return jsonify({"error": "No agent available to process this request"}), 500

    except ClientError as e:
        return jsonify({"error": str(e)}), 500
    except requests.RequestException as e:
        return jsonify({"error": "Agent proxy request failed", "details": str(e)}), 502
    except Exception as e:
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

@app.route("/ai/substeps", methods=["POST"])
def substeps():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Missing token"}), 401
    try:
        decoded = jwt.decode(token, app.config["JWT_SECRET"], algorithms=["HS256"])
        userId = decoded["userId"]
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401

    try:
        payload = request.get_json() or {}
        step = payload.get("step")
        ticket = payload.get("ticket", None)
        top_k = int(payload.get("top_k", 3))

        if not step:
            return jsonify({"error": "step (string) is required"}), 400

        # Prefer master_agent tool
        if MASTER_AVAILABLE and generate_substeps_tool is not None:
            try:
                ctx_json = json.dumps(ticket or {})
                tool_res = generate_substeps_tool(step, ctx_json, top_k=top_k)
                if isinstance(tool_res, dict) and tool_res.get("ok"):
                    return jsonify({"ok": True, "source": "master_agent", "result": tool_res.get("result")}), 200
                else:
                    return jsonify({"ok": False, "error": tool_res.get("error", "tool failed")}), 500
            except Exception as e:
                logger.exception("master_agent.generate_substeps_tool failed: %s", e)
                # fallthrough to local agent if present

        # Fallback to in-process substeps agent
        if AGENT_SUBSTEPS_AVAILABLE:
            result = suggest_substeps_for_resolution_step(step, ticket_context=ticket, top_k=top_k)
            return jsonify({"ok": True, "source": "import", "result": result}), 200

        # Fallback: use master_agent.process_request freeform
        if MASTER_AVAILABLE:
            try:
                process_request = getattr(master_agent_module, "process_request", None)
                if callable(process_request):
                    instruction = f"Generate UI-level substeps for resolution step: {json.dumps(step)}. Ticket context: {json.dumps(ticket or {})}. Return JSON only."
                    resp = process_request(instruction)
                    return jsonify({"ok": True, "source": "master_agent.process_request", "result": resp.get("result")}), 200
            except Exception:
                logger.exception("master_agent.process_request failed for substeps")

        return jsonify({"error": "Substeps agent not available on server"}), 500

    except ClientError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": "Substeps generation failed", "details": str(e)}), 500

@app.route("/ai/chat", methods=["POST"])
def chat_route():
    # authenticate
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Missing token"}), 401
    try:
        decoded = jwt.decode(token, app.config["JWT_SECRET"], algorithms=["HS256"])
        userId = decoded["userId"]
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401

    body = request.get_json(silent=True) or {}
    question = (body.get("question") or body.get("q") or "").strip()
    conversation = body.get("conversation", []) or []
    ticket_context = body.get("ticket_context", None)
    top_k = int(body.get("top_k", 5))

    if not question:
        return jsonify({"error": "Missing 'question' in request"}), 400

    try:
        # prefer master_agent chat tool
        if MASTER_AVAILABLE and chat_with_agent_tool is not None:
            try:
                conv_json = json.dumps(conversation or [])
                ctx_json = json.dumps(ticket_context or {})
                tool_res = chat_with_agent_tool(conv_json, question, ctx_json, top_k=top_k)
                if isinstance(tool_res, dict) and tool_res.get("ok"):
                    return jsonify({"result": tool_res.get("result"), "error": None}), 200
                else:
                    return jsonify({"result": None, "error": tool_res.get("error", "tool failed")}), 500
            except Exception as e:
                logger.exception("master_agent.chat_with_agent_tool failed: %s", e)

        # fallback to chat_agent if available
        if CHAT_AGENT_AVAILABLE:
            resp = chat_with_agent(conversation=conversation, question=question, ticket_context=ticket_context, top_k=top_k)
            return jsonify({"result": resp, "error": None}), 200

        # final fallback: ask master_agent.process_request freeform
        if MASTER_AVAILABLE:
            try:
                process_request = getattr(master_agent_module, "process_request", None)
                if callable(process_request):
                    instruction = f"Conversational request. Transcript: {json.dumps(conversation)}. Question: {question}. Ticket context: {json.dumps(ticket_context or {})}"
                    resp = process_request(instruction)
                    return jsonify({"result": resp.get("result"), "error": None}), 200
            except Exception:
                logger.exception("master_agent.process_request fallback failed for chat")

        return jsonify({"result": None, "error": "No chat agent available"}), 500
    except Exception as e:
        return jsonify({"result": None, "error": str(e)}), 500

# KB endpoints unchanged (they still use kb_store)
@app.route("/kg/health", methods=["GET"])
def kg_health():
    try:
        status = kb_get_status()
        return jsonify({"ok": True, "status": status}), 200
    except Exception as e:
        logger.exception("kg_health error")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/kg/tickets", methods=["GET"])
def kg_tickets():
    try:
        tickets = kb_get_tickets()
        return jsonify({"tickets": tickets}), 200
    except Exception as e:
        logger.exception("kg_tickets error")
        return jsonify({"error": str(e)}), 500

@app.route("/kg/ticket/<ticket_id>", methods=["GET"])
def kg_ticket(ticket_id):
    try:
        t = kb_find_ticket(ticket_id)
        if not t:
            return jsonify({"error": "Ticket not found"}), 404
        return jsonify({"ticket": t}), 200
    except Exception as e:
        logger.exception("kg_ticket error")
        return jsonify({"error": str(e)}), 500

@app.route("/kg/search", methods=["GET"])
def kg_search():
    q = request.args.get("q", "").strip()
    try:
        top_k = int(request.args.get("top_k", "10"))
    except Exception:
        top_k = 10
    if not q:
        return jsonify({"error": "q parameter required"}), 400
    try:
        hits = kb_search(q, top_k=top_k)
        return jsonify({"query": q, "count": len(hits), "hits": hits}), 200
    except Exception as e:
        logger.exception("kg_search error")
        return jsonify({"error": str(e)}), 500

@app.route("/kg/refresh", methods=["POST", "GET"])
def kg_refresh():
    try:
        result = kb_reload()
        return jsonify(result), 200
    except Exception as e:
        logger.exception("kg_refresh error")
        return jsonify({"error": str(e)}), 500

@app.route("/kg/graph", methods=["GET"])
def kg_graph():
    try:
        kg = kb_get_kg()
        return jsonify(kg), 200
    except Exception as e:
        logger.exception("kg_graph error")
        return jsonify({"error": str(e)}), 500

@app.route("/kg/node/<path:node_id>", methods=["GET"])
def kg_node(node_id):
    try:
        node = kb_find_node(node_id)
        if not node:
            return jsonify({"error": "Node not found"}), 404
        edges = kb_find_edges(node_id)
        return jsonify({"node": node, "edges": edges}), 200
    except Exception as e:
        logger.exception("kg_node error")
        return jsonify({"error": str(e)}), 500

@app.route("/kg/nodes/search", methods=["GET"])
def kg_nodes_search():
    q = request.args.get("q", "").strip()
    try:
        top_k = int(request.args.get("top_k", "20"))
    except Exception:
        top_k = 20
    if not q:
        return jsonify({"error": "q parameter required"}), 400
    try:
        hits = kb_search_nodes(q, top_k=top_k)
        return jsonify({"query": q, "count": len(hits), "hits": hits}), 200
    except Exception as e:
        logger.exception("kg_nodes_search error")
        return jsonify({"error": str(e)}), 500

@app.route("/ml/predict", methods=["POST"])
def sagemaker_predict():
    """
    Call a deployed Amazon SageMaker endpoint.
    Request body accepts either:
      - {"ticketId": "..."}  OR
      - {"ticket": {...}}     (a full ticket dict)
    Optional body fields:
      - "endpoint": "my-endpoint-name"  (overrides app.config["SAGEMAKER_ENDPOINT"])
      - "as_list": true/false            (if true, we send a list of tickets; default false)

    Returns JSON prediction returned by the model.
    """
    # auth
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Missing token"}), 401
    try:
        decoded = jwt.decode(token, app.config["JWT_SECRET"], algorithms=["HS256"])
        userId = decoded["userId"]
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401

    try:
        body = request.get_json(silent=True) or {}
        ticket_id = body.get("ticketId")
        ticket_payload = body.get("ticket")
        endpoint_name = body.get("endpoint") or app.config.get("SAGEMAKER_ENDPOINT")
        as_list = bool(body.get("as_list", False))

        if not endpoint_name:
            return jsonify({"error": "SageMaker endpoint not configured (provide 'endpoint' in request or set app.config['SAGEMAKER_ENDPOINT'])"}), 400

        # If ticketId provided, fetch from FixellaTickets table
        if ticket_id and not ticket_payload:
            tickets_table = dynamodb.Table("FixellaTickets")
            resp = tickets_table.get_item(Key={"ticketId": ticket_id})
            if "Item" not in resp:
                return jsonify({"error": "Ticket not found"}), 404
            ticket_payload = resp["Item"]

        if not ticket_payload:
            return jsonify({"error": "ticket or ticketId required"}), 400

        # Build payload to send to the model. The model's input_fn supports either
        # an object (it will wrap to a list) or a list of objects.
        payload_to_send = ticket_payload if not as_list else [ticket_payload]

        runtime = boto3.client("sagemaker-runtime", region_name=app.config.get("AWS_REGION"))
        # invoke endpoint
        response = runtime.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="application/json",
            Accept="application/json",
            Body=json.dumps(payload_to_send),
        )

        # read and parse response body
        resp_bytes = response["Body"].read()
        try:
            resp_text = resp_bytes.decode("utf-8")
        except Exception:
            resp_text = str(resp_bytes)

        try:
            prediction = json.loads(resp_text)
        except Exception:
            # return raw text if not JSON
            prediction = resp_text

        return jsonify({"ok": True, "endpoint": endpoint_name, "prediction": prediction}), 200

    except ClientError as e:
        # AWS-level errors
        return jsonify({"error": "AWS client error", "details": str(e)}), 500
    except Exception as e:
        # generic
        logger.exception("sagemaker_predict error")
        return jsonify({"error": "Prediction failed", "details": str(e)}), 500
    
# ------ helper: download s3 uri to local (same logic as your inference.py)
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
    s3 = boto3.client("s3", region_name=app.config.get("AWS_REGION"))
    s3.download_file(bucket, key, local_path)
    return local_path

# small flatten_ticket helper (adapted from your inference.py)
def flatten_ticket_for_explainer(ticket: dict) -> dict:
    # minimal flattening used for prediction and explanation
    flat = {}
    flat["ticketId"] = ticket.get("ticketId")
    flat["displayId"] = ticket.get("displayId")
    flat["subject"] = (ticket.get("subject") or ticket.get("title") or "").strip()
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
    flat["priority"] = ticket.get("priority") or "Unknown"
    flat["impact"] = ticket.get("impact") or "Unknown"
    flat["urgency"] = ticket.get("urgency") or "Unknown"
    flat["category"] = ticket.get("category") or "Unknown"
    flat["subcategory"] = ticket.get("subcategory") or "Unknown"
    flat["cause"] = ticket.get("cause")
    flat["subcause"] = ticket.get("subcause")
    try:
        flat["worklogTimespent"] = float(ticket.get("worklogTimespent") or 0.0)
    except Exception:
        flat["worklogTimespent"] = 0.0
    flat["followers_count"] = len(ticket.get("followers") or [])
    created = None
    try:
        created = ticket.get("createdTime")
        # attempt parse if string
        if isinstance(created, str) and created:
            from datetime import datetime as _dt
            try:
                created = _dt.fromisoformat(created)
            except Exception:
                created = None
    except Exception:
        created = None
    flat["created_hour"] = created.hour if created else -1
    flat["created_weekday"] = created.weekday() if created else -1
    flat["subject_len"] = len(flat["subject"])
    flat["resolution_len"] = len(flat["resolution_text"])
    flat["has_followers"] = int(flat["followers_count"] > 0)
    return flat

# ------ small cache for loaded model to avoid reload on every explain
_EXPLAINER_MODEL = None
def _load_local_model_once():
    global _EXPLAINER_MODEL
    if _EXPLAINER_MODEL is not None:
        return _EXPLAINER_MODEL

    # Try direct file path first
    explicit = app.config.get("MODEL_FILE_PATH") or os.environ.get("MODEL_FILE_PATH")
    if explicit and os.path.exists(explicit):
        _EXPLAINER_MODEL = joblib.load(explicit)
        return _EXPLAINER_MODEL

    # Try MODEL_S3_URI
    s3_uri = app.config.get("MODEL_S3_URI") or os.environ.get("MODEL_S3_URI") or os.environ.get("MODEL_S3_PATH")
    if s3_uri:
        tmpf = os.path.join(tempfile.gettempdir(), os.path.basename(s3_uri))
        _download_s3_uri_to_local(s3_uri, tmpf)
        _EXPLAINER_MODEL = joblib.load(tmpf)
        return _EXPLAINER_MODEL

    raise FileNotFoundError("Model file not found. Set MODEL_FILE_PATH or MODEL_S3_URI in config/env")

@app.route("/ml/explain", methods=["POST"])
def sagemaker_explain():
    import sys, traceback, json
    from botocore.exceptions import ClientError as BotoClientError

    def eprint(*args, **kwargs):
        print(*args, file=sys.stderr, flush=True, **kwargs)

    token = request.headers.get("Authorization")
    if not token:
        eprint("[EXPLAIN] Missing token")
        return jsonify({"error": "Missing token"}), 401

    try:
        decoded = jwt.decode(token, app.config["JWT_SECRET"], algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        eprint("[EXPLAIN] Token expired")
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        eprint("[EXPLAIN] Invalid token")
        return jsonify({"error": "Invalid token"}), 401

    try:
        body = request.get_json(silent=True) or {}
        ticket_id = body.get("ticketId")
        ticket_payload = body.get("ticket")
        top_k = int(body.get("top_k", 6))

        eprint(f"[EXPLAIN] Request body keys: {list(body.keys())} ticketId={ticket_id} top_k={top_k}")

        if ticket_id and not ticket_payload:
            eprint(f"[EXPLAIN] Fetching ticket {ticket_id} from DynamoDB")
            tickets_table = dynamodb.Table("FixellaTickets")
            resp = tickets_table.get_item(Key={"ticketId": ticket_id})
            if "Item" not in resp:
                eprint(f"[EXPLAIN] Ticket {ticket_id} not found")
                return jsonify({"error": "Ticket not found"}), 404
            ticket_payload = resp["Item"]
            eprint("[EXPLAIN] Fetched ticket payload")

        if not ticket_payload:
            eprint("[EXPLAIN] No ticket payload provided")
            return jsonify({"error": "ticket or ticketId required"}), 400

        row = flatten_ticket_for_explainer(ticket_payload)
        eprint("[EXPLAIN] Flattened ticket row keys:", list(row.keys()))

        # load model (cached)
        try:
            eprint("[EXPLAIN] Loading model via _load_local_model_once()")
            model = _load_local_model_once()
            eprint("[EXPLAIN] Model loaded:", type(model).__name__)
        except Exception as e:
            eprint("[EXPLAIN] Local model load failed:", str(e))
            eprint(traceback.format_exc())
            return jsonify({"error": "Local model load failed", "details": str(e)}), 500

        feature_cols = [
            "subject", "resolution_text",
            "priority", "impact", "urgency", "category", "subcategory", "technician_name",
            "followers_count", "worklogTimespent", "created_hour", "created_weekday",
            "subject_len", "resolution_len", "has_followers"
        ]
        X_row = {c: row.get(c, None) for c in feature_cols}
        eprint("[EXPLAIN] X_row prepared")

        # Prepare pandas DataFrame for SHAP / background (SHAP expects array/DF)
        try:
            import pandas as pd
            import numpy as np
        except Exception as e:
            eprint("[EXPLAIN] pandas/numpy import failed:", str(e))
            eprint(traceback.format_exc())
            return jsonify({"error": "Server missing pandas/numpy", "details": str(e)}), 500

        X_input_df = pd.DataFrame([X_row])
        # background: default to empty strings / zeros matching types used earlier
        background = {}
        for c in feature_cols:
            if c in ("followers_count", "worklogTimespent", "created_hour", "created_weekday", "subject_len", "resolution_len", "has_followers"):
                background[c] = 0.0
            else:
                background[c] = ""
        bg_df = pd.DataFrame([background])

        eprint("[EXPLAIN] Prepared X_input_df and bg_df with columns:", list(X_input_df.columns))

        # Helper wrapper: accepts array-like input, returns probability for class 1 as 1D numpy array
        def predict_prob_one(arr_like):
            """
            arr_like can be numpy array or pandas DataFrame. We convert to DataFrame with correct columns.
            Return: 1D numpy array of probabilities for class 1.
            """
            try:
                if isinstance(arr_like, np.ndarray):
                    df = pd.DataFrame(arr_like, columns=X_input_df.columns)
                elif isinstance(arr_like, pd.DataFrame):
                    df = arr_like.reindex(columns=X_input_df.columns)
                else:
                    # try converting list of dicts or list-of-lists
                    df = pd.DataFrame(arr_like)
                    df = df.reindex(columns=X_input_df.columns)
                # Ensure dtypes / fill missing as model expects; apply similar conversions as training pipeline does
                # Let the pipeline handle types (it contains imputers/transformers)
                probs = model.predict_proba(df)
                # If binary classification, pick class 1 column, else attempt column 1
                if probs.ndim == 1:
                    return np.array(probs)
                elif probs.shape[1] > 1:
                    return np.asarray(probs[:, 1])
                else:
                    return np.asarray(probs[:, 0])
            except Exception as e:
                eprint("[EXPLAIN] predict_prob_one error:", str(e))
                eprint(traceback.format_exc())
                # raise to surface to SHAP if it fails
                raise

        # Try SHAP explanation using a callable + DataFrame masker
        try:
            eprint("[EXPLAIN] Attempting to import shap")
            import shap  # type: ignore
            eprint("[EXPLAIN] shap version:", getattr(shap, "__version__", "unknown"))

            # Prefer using a callable explainer with DataFrame masker (works for pipelines)
            try:
                eprint("[EXPLAIN] Creating shap.Explainer with callable + DataFrame masker (recommended)")
                masker = shap.maskers.DataFrame(bg_df)
                explainer = shap.Explainer(predict_prob_one, masker=masker)
                eprint("[EXPLAIN] shap.Explainer created:", type(explainer).__name__)
            except Exception as e_expl:
                eprint("[EXPLAIN] shap.Explainer(...) failed, will try KernelExplainer fallback:", str(e_expl))
                eprint(traceback.format_exc())
                # KernelExplainer expects background as numpy or DataFrame
                try:
                    explainer = shap.KernelExplainer(predict_prob_one, bg_df)
                    eprint("[EXPLAIN] shap.KernelExplainer created")
                except Exception as e_k:
                    eprint("[EXPLAIN] KernelExplainer creation failed:", str(e_k))
                    eprint(traceback.format_exc())
                    raise

            eprint("[EXPLAIN] Running explainer on X_input_df (this may be slow for KernelExplainer)...")
            shap_values = explainer(X_input_df)  # compute SHAP values
            eprint("[EXPLAIN] shap_values obtained, type:", type(shap_values).__name__)

            # Extract per-feature contributions for class 1 (we used predict_prob_one)
            values = None
            base_values = None
            try:
                if hasattr(shap_values, "values") and shap_values.values is not None:
                    arr = np.array(shap_values.values)
                    eprint("[EXPLAIN] shap values array ndim/shape:", getattr(arr, "ndim", None), getattr(arr, "shape", None))
                    if arr.ndim == 2:
                        # (n_samples, n_features)
                        values = arr[0].tolist()
                    elif arr.ndim == 3:
                        # (n_classes, n_samples, n_features) — pick class 1 if exists
                        class_idx = 1 if arr.shape[0] > 1 else 0
                        values = arr[class_idx, 0, :].tolist()
                    else:
                        values = arr.flatten().tolist()
                # base values
                if hasattr(shap_values, "base_values"):
                    bv = shap_values.base_values
                    barr = np.array(bv)
                    if barr.ndim == 0:
                        base_values = float(barr)
                    elif barr.ndim == 1:
                        base_values = float(barr[0])
                    else:
                        base_values = float(barr.flatten()[0])
            except Exception as evals:
                eprint("[EXPLAIN] Error extracting shap values/base:", str(evals))
                eprint(traceback.format_exc())
                values = None
                base_values = None

            feature_contribs = []
            if values is not None:
                eprint("[EXPLAIN] Building contributions from shap values, count:", len(values))
                for feat_name, contrib in zip(feature_cols, values):
                    try:
                        contrib_f = float(contrib)
                    except Exception:
                        contrib_f = 0.0
                    feature_contribs.append({
                        "feature": feat_name,
                        "value": X_row.get(feat_name),
                        "contribution": contrib_f,
                        "abs": abs(contrib_f)
                    })
                feature_contribs = sorted(feature_contribs, key=lambda x: -x["abs"])[:top_k]
            else:
                eprint("[EXPLAIN] No shap numeric values extracted; returning empty contributions")
                feature_contribs = []

            eprint("[EXPLAIN] Returning SHAP explanations:", feature_contribs)
            return jsonify({
                "ok": True,
                "ticketId": row.get("ticketId"),
                "base_value": base_values,
                "explanations": feature_contribs
            }), 200

        except Exception as e_shap:
            eprint("[EXPLAIN] SHAP explanation failed:", str(e_shap))
            eprint(traceback.format_exc())
            eprint("[EXPLAIN] Falling back to deterministic per-feature delta vs background (single-sample safe)")

            # fallback: for each feature, set to background value and measure change in probability
            try:
                baseline_prob = float(predict_prob_one(X_input_df)[0])
                eprint("[EXPLAIN] baseline_prob:", baseline_prob)
                per_feature = []
                for feat in feature_cols:
                    try:
                        modified = X_input_df.copy(deep=True)
                        modified[feat] = background[feat]
                        new_prob = float(predict_prob_one(modified)[0])
                        contribution = baseline_prob - new_prob
                        per_feature.append({
                            "feature": feat,
                            "value": X_row.get(feat),
                            "contribution": float(contribution),
                            "abs": abs(float(contribution))
                        })
                        eprint(f"[EXPLAIN] feat={feat} baseline={baseline_prob:.6f} new={new_prob:.6f} contrib={contribution:.6f}")
                    except Exception as fe:
                        eprint("[EXPLAIN] Error computing delta for feature", feat, str(fe))
                        eprint(traceback.format_exc())
                per_feature = sorted(per_feature, key=lambda x: -x["abs"])[:top_k]
                eprint("[EXPLAIN] Returning delta-based explanations:", per_feature)
                return jsonify({"ok": True, "ticketId": row.get("ticketId"), "base_value": baseline_prob, "explanations": per_feature}), 200
            except Exception as ex_final:
                eprint("[EXPLAIN] Final fallback failed:", str(ex_final))
                eprint(traceback.format_exc())
                return jsonify({"ok": False, "error": "Could not compute explanations", "details": str(ex_final)}), 500

    except FileNotFoundError as e:
        eprint("[EXPLAIN] FileNotFoundError:", str(e))
        eprint(traceback.format_exc())
        return jsonify({"error": str(e)}), 500
    except BotoClientError as e:
        eprint("[EXPLAIN] AWS ClientError:", str(e))
        eprint(traceback.format_exc())
        return jsonify({"error": "AWS client error", "details": str(e)}), 500
    except Exception as e:
        eprint("[EXPLAIN] Unexpected error in sagemaker_explain:", str(e))
        eprint(traceback.format_exc())
        logger.exception("sagemaker_explain error")
        return jsonify({"error": "Explain failed", "details": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
