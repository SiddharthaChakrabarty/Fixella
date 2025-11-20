# test_mcp_sigv4.py
import asyncio
import os
import urllib.parse
import boto3
from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4Auth
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# === CONFIGURE ===
AGENT_ARN = os.getenv("AGENT_ARN", "arn:aws:bedrock-agentcore:us-east-2:521818209921:runtime/FixellaAgent-tFe24l5vaJ")
REGION = os.getenv("REGION", "us-east-2")

# URL encode the ARN
ENC_ARN = urllib.parse.quote(AGENT_ARN, safe="")
URL = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{ENC_ARN}/invocations?qualifier=DEFAULT"

# Build an AWSRequest for signing
# Note: data/body must be bytes or str; using empty body is fine for initial handshake
aws_request = AWSRequest(method="POST", url=URL, data=b"")
# Get credentials from boto3 session (uses env vars / profile / instance role automatically)
session = boto3.session.Session()
credentials = session.get_credentials().get_frozen_credentials()

# Sign the request for service "bedrock-agentcore"
SigV4Auth(credentials, "bedrock-agentcore", REGION).add_auth(aws_request)

# Extract signed headers
signed_headers = dict(aws_request.headers.items())
# Ensure Content-Type present for mcp client
signed_headers.setdefault("Content-Type", "application/json")

print("Invoking URL:", URL)
print("Signed headers (partial):")
for k in ["Authorization", "X-Amz-Date", "Host", "Content-Type", "X-Amz-Security-Token"]:
    if k in signed_headers:
        print(f"  {k}: {signed_headers[k]}")

async def run():
    # Pass the signed headers to streamablehttp_client
    async with streamablehttp_client(URL, signed_headers, timeout=120, terminate_on_close=False) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # list tools
            tools = await session.list_tools()
            print("TOOLS:", tools)

            # example tool calls (adapt to your available tools)
            try:
                gen_args = {
                    "resolution_step": "Restart the database service",
                    "ticket_context_json": "{\"ticket_id\": 1234, \"issue\": \"DB unreachable\", \"env\": \"prod\"}",
                    "top_k": 3
                }
                print("\nCalling generate_substeps...")
                r = await session.call_tool("generate_substeps", gen_args)
                print("generate_substeps ->", r)
            except Exception as e:
                print("Tool call error:", e)

if __name__ == "__main__":
    asyncio.run(run())
