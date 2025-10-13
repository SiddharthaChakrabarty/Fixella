# package_model_s3.py
import os
import boto3
import tempfile
import tarfile

# ---------- CONFIG ----------
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
s3 = boto3.client("s3", region_name=AWS_REGION)

# Replace these with your actual S3 locations
SOURCE_JOBLIB_S3 = "s3://fixella-bucket-superhack/models/ticket_escalation_model.joblib"
# Where to upload the packaged model tar.gz for SageMaker to use
MODEL_TAR_S3 = "s3://fixella-bucket-superhack/models/ticket_escalation_model.tar.gz"

def parse_s3(s3_uri):
    assert s3_uri.startswith("s3://")
    parts = s3_uri[5:].split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""
    return bucket, key

def download(s3_uri, local_path):
    bucket, key = parse_s3(s3_uri)
    s3.download_file(bucket, key, local_path)

def upload(local_path, s3_uri):
    bucket, key = parse_s3(s3_uri)
    s3.upload_file(local_path, bucket, key)

def package_joblib_to_tar(source_joblib_s3, dest_tar_s3):
    tmpdir = tempfile.mkdtemp()
    local_joblib = os.path.join(tmpdir, "model.joblib")   # name inside tar should be model.joblib
    local_tar = os.path.join(tmpdir, "model.tar.gz")

    print("Downloading joblib from:", source_joblib_s3)
    download(source_joblib_s3, local_joblib)

    # create tar.gz containing model.joblib at the root
    with tarfile.open(local_tar, "w:gz") as tar:
        tar.add(local_joblib, arcname="model.joblib")

    print("Uploading packaged tar to:", dest_tar_s3)
    upload(local_tar, dest_tar_s3)
    print("Done. Packaged artifact uploaded to:", dest_tar_s3)
    return dest_tar_s3

if __name__ == "__main__":
    package_joblib_to_tar(SOURCE_JOBLIB_S3, MODEL_TAR_S3)
