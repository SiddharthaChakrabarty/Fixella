from flask import Flask, request, jsonify
import boto3
import bcrypt
import jwt
import uuid
import datetime
from botocore.exceptions import ClientError
from flask_cors import CORS
from boto3.dynamodb.conditions import Key

app = Flask(__name__)
CORS(app) 

app.config['JWT_SECRET'] = "hello123"
app.config['AWS_REGION'] = "us-east-1"
app.config['DYNAMO_TABLE'] = "FixellaUsers"

dynamodb = boto3.resource('dynamodb', region_name=app.config['AWS_REGION'])
table = dynamodb.Table(app.config['DYNAMO_TABLE'])

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
            ExpressionAttributeValues={":email": email}
        )
        if response['Items']:
            return jsonify({"error": "User already exists"}), 400

        # Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

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
            ExpressionAttributeValues={":email": email}
        )
        if not response['Items']:
            return jsonify({"error": "User not found"}), 404

        user = response['Items'][0]

        # Verify password
        if not bcrypt.checkpw(password.encode('utf-8'), user['passwordHash'].encode('utf-8')):
            return jsonify({"error": "Invalid credentials"}), 401

        # Generate JWT token
        token = jwt.encode(
            {
                "userId": user["userId"],
                "email": user["email"],
                "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=6)
            },
            app.config["JWT_SECRET"],
            algorithm="HS256"
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
        return jsonify({
            "userId": user["userId"],
            "email": user["email"],
            "name": user.get("name"),
        }), 200

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
            ExpressionAttributeValues={":tid": userId}
        )

        tickets = response.get("Items", [])

        # Map tickets to a cleaner structure for frontend
        ticket_list = []
        for t in tickets:
            ticket_list.append({
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
                "worklogTimespent": t.get("worklogTimespent", "0.00")
            })

        return jsonify({"tickets": ticket_list}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except ClientError as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
