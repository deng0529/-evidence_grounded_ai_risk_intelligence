"""R2 S3-compatible immutable storage with a small injectable client boundary."""

from typing import Protocol, TypedDict

from botocore.exceptions import BotoCoreError, ClientError

from risk_intelligence.config import Settings
from risk_intelligence.domain.evidence import RawEvidence
from .objects import EvidenceIntegrityError, StorageAccessError, validate_object_path, verify_checksum


class ResponseBody(Protocol):
    """Readable and closeable S3 response body."""

    def read(self) -> bytes:
        """Read exact response bytes."""
        ...

    def close(self) -> None:
        """Release the response stream."""
        ...


class ObjectResponse(TypedDict):
    """Only the S3 response fields needed for integrity checking."""

    Body: ResponseBody
    ContentLength: int


class S3Client(Protocol):
    """Minimal injectable S3 operations; tests never create a network client."""

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str,
                   IfNoneMatch: str, Metadata: dict[str, str]) -> object:
        """Create only when the destination does not exist."""
        ...

    def get_object(self, *, Bucket: str, Key: str) -> ObjectResponse:
        """Read an object, or raise a classified SDK error."""
        ...


class R2Storage:
    """Immutable objects using conditional PUT; never HEAD plus unconditional PUT."""

    def __init__(self, client: S3Client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> "R2Storage":
        """Construct an explicitly credentialed client; no ambient credential lookup."""
        import boto3
        from botocore.config import Config

        if (settings.evidence_storage_backend != "r2" or not settings.r2_access_key_id
                or not settings.r2_secret_access_key or not settings.r2_account_id or not settings.r2_bucket_name):
            raise StorageAccessError("R2 configuration is incomplete")
        try:
            client = boto3.client(
                "s3", endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
                region_name="auto", aws_access_key_id=settings.r2_access_key_id.get_secret_value(),
                aws_secret_access_key=settings.r2_secret_access_key.get_secret_value(),
                config=Config(signature_version="s3v4", connect_timeout=10, read_timeout=30,
                              retries={"total_max_attempts": 1},
                              request_checksum_calculation="when_required", response_checksum_validation="when_required"),
            )
        except (BotoCoreError, ValueError):
            raise StorageAccessError("R2 client configuration failed") from None
        return cls(client, settings.r2_bucket_name)

    def read(self, object_path: str) -> bytes:
        """Read exact bytes; only NoSuchKey is absence, not permission or bucket errors."""
        validate_object_path(object_path)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=object_path)
            body = response["Body"]
            try:
                content = body.read()
            finally:
                body.close()
            if not isinstance(content, bytes) or len(content) != response["ContentLength"]:
                raise EvidenceIntegrityError("R2 response length mismatch")
            return content
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "NoSuchKey":
                raise FileNotFoundError("Raw evidence object is absent") from None
            raise StorageAccessError("R2 object read failed") from None
        except (BotoCoreError, OSError):
            raise StorageAccessError("R2 object read failed") from None

    def put(self, evidence: RawEvidence, content: bytes) -> None:
        """Conditionally create and verify bytes; reject conflicting existing content."""
        evidence = RawEvidence.model_validate(evidence)
        validate_object_path(evidence.object_path)
        verify_checksum(content, evidence.checksum)
        try:
            self._client.put_object(
                Bucket=self._bucket, Key=evidence.object_path, Body=content,
                ContentType=evidence.media_type, IfNoneMatch="*",
                Metadata={"sha256": evidence.checksum},
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "PreconditionFailed":
                raise StorageAccessError("R2 conditional object write failed") from None
            if self.read(evidence.object_path) != content:
                raise EvidenceIntegrityError("Immutable R2 object already contains different bytes") from None
        except (BotoCoreError, OSError):
            raise StorageAccessError("R2 conditional object write failed") from None
        verify_checksum(self.read(evidence.object_path), evidence.checksum)
