# ingest_s3.py
import os
import json
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError


def fetch_kb_from_s3(
    bucket: str, key: str, region: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Fetch JSON KB from S3 and return it as a Python object (list/dict).
    Raises botocore.exceptions.ClientError on failure.
    """
    s3 = boto3.client("s3", region_name=region) if region else boto3.client("s3")
    obj = s3.get_object(Bucket=bucket, Key=key)
    raw = obj["Body"].read()
    return json.loads(raw)


def write_local_kb(path: str, data: List[Dict[str, Any]]):
    """
    Write downloaded KB to local file (useful as a local cache / fallback).
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # simple CLI usage
    import argparse

    p = argparse.ArgumentParser(description="Fetch it_tickets_kb.json from S3")
    p.add_argument("--bucket", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--region", default=None)
    p.add_argument("--out", default="it_tickets_kb.json", help="Local path to write KB")
    args = p.parse_args()

    try:
        kb = fetch_kb_from_s3(args.bucket, args.key, args.region)
        write_local_kb(args.out, kb)
        print(f"Fetched {len(kb)} top-level items and wrote to {args.out}")
    except ClientError as ce:
        print("S3 ClientError:", ce)
    except Exception as e:
        print("Error:", e)
