# deploy_model.py
import sagemaker
from sagemaker.sklearn.model import SKLearnModel

# ---------- CONFIG ----------
sagemaker_session = sagemaker.Session()
role = "arn:aws:iam::058264280347:role/service-role/AmazonSageMaker-ExecutionRole-20251013T193270"  # replace when needed

# The model artifact you uploaded to S3.
# Option A: a model.tar.gz containing model.joblib (typical SageMaker artifact)
MODEL_TAR_S3 = "s3://fixella-bucket-superhack/models/ticket_escalation_model.tar.gz"
# Option B: a single joblib on S3 (the inference loader supports downloading via MODEL_S3_URI)
MODEL_JOBLIB_S3 = "s3://fixella-bucket-superhack/models/ticket_escalation_model.joblib"

ENTRY_POINT = "inference.py"   # inference file shown above
FRAMEWORK_VERSION = "1.2-1"    # IMPORTANT: use scikit-learn 1.2 container to match saved pipeline
PYTHON_VERSION = "py3"

INSTANCE_TYPE = "ml.m5.large"
ENDPOINT_NAME = "ticket-escalation-endpoint-4"

# Provide MODEL_S3_URI in env as a fallback in case the tarball layout differs.
env = {
    # If you used a plain .joblib artifact (not a model.tar.gz), point MODEL_S3_URI to that joblib.
    "MODEL_S3_URI": MODEL_JOBLIB_S3
}

# Create SKLearnModel:
sk_model = SKLearnModel(
    model_data=MODEL_TAR_S3,   # can be tar.gz or joblib; model_fn in inference.py will try both
    role=role,
    entry_point=ENTRY_POINT,
    framework_version=FRAMEWORK_VERSION,
    py_version=PYTHON_VERSION,
    sagemaker_session=sagemaker_session,
    env=env
)

# Deploy
predictor = sk_model.deploy(
    initial_instance_count=1,
    instance_type=INSTANCE_TYPE,
    endpoint_name=ENDPOINT_NAME,
    wait=True
)

# configure JSON serializer/deserializer
from sagemaker.serializers import JSONSerializer
from sagemaker.deserializers import JSONDeserializer
predictor.serializer = JSONSerializer()
predictor.deserializer = JSONDeserializer()

print("Deployed endpoint:", ENDPOINT_NAME)
print("Predictor ready for invocations.")
