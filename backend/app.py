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

# === try to import the agent function if available ===
try:
    # put your agent file (the long script) into the project as `agent_service.py`
    # and ensure it exposes `suggest_resolution_for_ticket`
    from agents.resolution_steps_agent import suggest_resolution_for_ticket  # optional

    AGENT_IMPORT_AVAILABLE = True
except Exception:
    AGENT_IMPORT_AVAILABLE = False

try:
    # the new substeps agent (strands + Bedrock)
    from agents.agent_substeps_llm import suggest_substeps_for_resolution_step

    AGENT_SUBSTEPS_AVAILABLE = True
except Exception:
    AGENT_SUBSTEPS_AVAILABLE = False
    
from agents.chat_agent import chat_with_agent

app = Flask(__name__)
CORS(app)

app.config["JWT_SECRET"] = "hello123"
app.config["AWS_REGION"] = "us-east-1"
app.config["DYNAMO_TABLE"] = "FixellaUsers"

dynamodb = boto3.resource("dynamodb", region_name=app.config["AWS_REGION"])
table = dynamodb.Table(app.config["DYNAMO_TABLE"])


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

        # Option A: call agent function directly (if available/importable)
        if AGENT_IMPORT_AVAILABLE:
            # NOTE: this will run in-process and requires agent dependencies (boto3, strands, bedrock, AWS creds)
            suggestion = suggest_resolution_for_ticket(new_ticket, top_k=4)
            return jsonify({"ok": True, "source": "import", "result": suggestion}), 200

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

        if not AGENT_SUBSTEPS_AVAILABLE:
            return jsonify({"error": "Substeps agent not available on server"}), 500

        # Call the substeps agent (this runs in-process and requires strands/bedrock deps & AWS creds)
        result = suggest_substeps_for_resolution_step(
            step, ticket_context=ticket, top_k=top_k
        )

        return jsonify({"ok": True, "result": result}), 200

    except ClientError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # include message for debugging in dev; sanitize in production
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
        resp = chat_with_agent(conversation=conversation, question=question, ticket_context=ticket_context, top_k=top_k)
        return jsonify({"result": resp, "error": None}), 200
    except Exception as e:
        return jsonify({"result": None, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
