"""Local integration and deterministic R2 client-stub tests; no cloud access."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from io import BytesIO
import os
from pathlib import Path
import subprocess
import traceback

import boto3
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber
import pytest

from risk_intelligence.domain.evidence import RawEvidence, Source
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.storage.objects import (
    EvidenceIntegrityError, StorageAccessError, checksum, object_key, validate_object_path,
)
from risk_intelligence.storage.r2 import R2Storage

from conftest import EvidenceChain


def raw_metadata(content: bytes, path: str = "synthetic/object.bin") -> RawEvidence:
    return RawEvidence(raw_evidence_id="synthetic-raw", source_id="synthetic-source",
                       object_path=path, checksum=checksum(content), retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                       processing_run_id="synthetic-run", media_type="application/octet-stream")


@pytest.mark.parametrize("content", [b"", b"\x00\xff\r\nSYNTHETIC\x80", b"{}"])
def test_local_byte_round_trip_and_identical_retry(tmp_path: Path, content: bytes) -> None:
    storage = LocalStorage(tmp_path / "raw")
    raw = raw_metadata(content)
    storage.put(raw, content)
    storage.put(raw, content)
    assert storage.read(raw.object_path) == content
    assert list((tmp_path / "raw" / "synthetic").iterdir()) == [tmp_path / "raw" / raw.object_path]


def test_local_conflict_checksum_and_missing_object(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "raw")
    original = raw_metadata(b"original")
    storage.put(original, b"original")
    with pytest.raises(EvidenceIntegrityError):
        storage.put(raw_metadata(b"changed"), b"changed")
    with pytest.raises(EvidenceIntegrityError, match="SHA-256"):
        storage.put(original, b"wrong checksum")
    assert storage.read(original.object_path) == b"original"
    with pytest.raises(FileNotFoundError):
        storage.read("missing/nothing.bin")


@pytest.mark.parametrize("path", ["../escape", "/absolute", "C:/escape", "a/../escape", "a\\escape",
                                   "a//b", "a/./b", "a/b.", "a/CON.txt", "a/name:stream", ""])
def test_unsafe_paths_rejected_before_writes(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError):
        LocalStorage(tmp_path / "raw").put(raw_metadata(b"x", path), b"x")
    assert not (tmp_path / "raw").exists()


def test_symlink_or_junction_directory_cannot_escape_root(tmp_path: Path) -> None:
    root, outside = tmp_path / "raw", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "linked"
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                       check=True, capture_output=True)
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises((ValueError, OSError)):
            LocalStorage(root).put(raw_metadata(b"x", "linked/object.bin"), b"x")
        assert list(outside.iterdir()) == []
    finally:
        if os.name == "nt":
            link.rmdir()  # Remove only this test's junction, never its target.
        else:
            link.unlink()


def test_failed_publication_leaves_no_partial_final_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = LocalStorage(tmp_path / "raw")
    def fail_link(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic publication failure")
    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(OSError, match="publication"):
        storage.put(raw_metadata(b"complete bytes"), b"complete bytes")
    assert list((tmp_path / "raw" / "synthetic").iterdir()) == []


def test_concurrent_identical_writers_publish_once(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "raw")
    raw = raw_metadata(b"complete")
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: storage.put(raw, b"complete"), range(6)))
    assert storage.read(raw.object_path) == b"complete"
    assert len(list((tmp_path / "raw" / "synthetic").iterdir())) == 1


def test_key_uses_supplied_event_and_full_sha256(chain: EvidenceChain) -> None:
    key = object_key(chain.source, checksum(chain.content), chain.raw.media_type)
    assert key == chain.raw.object_path
    assert key.startswith("raw/v1/ZZ000001/COMPANIES_HOUSE_IXBRL/20260115T120000000000Z/source-test/")
    assert key.endswith(checksum(chain.content) + ".xhtml")
    assert object_key(chain.source, checksum(chain.content), chain.raw.media_type) == key
    assert validate_object_path(key)
    with pytest.raises(ValueError):
        object_key(chain.source, "not-a-digest", "application/json")


def make_client() -> object:
    return boto3.client("s3", region_name="auto", endpoint_url="https://synthetic.invalid",
                        aws_access_key_id="SYNTHETIC", aws_secret_access_key="SYNTHETIC")


def expected_put(raw: RawEvidence, content: bytes) -> dict[str, object]:
    return {"Bucket": "synthetic-bucket", "Key": raw.object_path, "Body": content,
            "ContentType": raw.media_type, "IfNoneMatch": "*", "Metadata": {"sha256": raw.checksum}}


def test_r2_real_sdk_stub_validates_conditional_put_and_read() -> None:
    client = make_client()
    raw = raw_metadata(b"synthetic bytes")
    with Stubber(client) as stub:
        stub.add_response("put_object", {}, expected_put(raw, b"synthetic bytes"))
        stub.add_response("get_object", {"Body": BytesIO(b"synthetic bytes"), "ContentLength": 15},
                          {"Bucket": "synthetic-bucket", "Key": raw.object_path})
        R2Storage(client, "synthetic-bucket").put(raw, b"synthetic bytes")
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("existing,matches", [(b"same", True), (b"different", False)])
def test_r2_conditional_conflict_verifies_existing_content(existing: bytes, matches: bool) -> None:
    client = make_client()
    raw = raw_metadata(b"same")
    with Stubber(client) as stub:
        stub.add_client_error("put_object", "PreconditionFailed", http_status_code=412,
                              expected_params=expected_put(raw, b"same"))
        stub.add_response("get_object", {"Body": BytesIO(existing), "ContentLength": len(existing)})
        if matches:
            stub.add_response("get_object", {"Body": BytesIO(existing), "ContentLength": len(existing)})
            R2Storage(client, "synthetic-bucket").put(raw, b"same")
        else:
            with pytest.raises(EvidenceIntegrityError):
                R2Storage(client, "synthetic-bucket").put(raw, b"same")
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("code,expected", [("NoSuchKey", FileNotFoundError), ("AccessDenied", StorageAccessError),
                                           ("NoSuchBucket", StorageAccessError), ("InternalError", StorageAccessError)])
def test_r2_missing_key_distinct_from_access_and_remote_failure(code: str, expected: type[Exception]) -> None:
    client = make_client()
    with Stubber(client) as stub:
        stub.add_client_error("get_object", code, service_message="SYNTHETIC_SECRET_MUST_NOT_LEAK")
        with pytest.raises(expected) as error:
            R2Storage(client, "synthetic-bucket").read("synthetic/object.bin")
        assert "SYNTHETIC_SECRET" not in "".join(traceback.format_exception(error.value))


def test_r2_checksum_mismatch_never_uploads() -> None:
    client = make_client()
    with Stubber(client):
        with pytest.raises(EvidenceIntegrityError):
            R2Storage(client, "synthetic-bucket").put(raw_metadata(b"original"), b"wrong")


def test_r2_detects_corrupt_readback_and_length() -> None:
    client = make_client()
    raw = raw_metadata(b"right")
    with Stubber(client) as stub:
        stub.add_response("put_object", {})
        stub.add_response("get_object", {"Body": BytesIO(b"wrong"), "ContentLength": 5})
        with pytest.raises(EvidenceIntegrityError, match="SHA-256"):
            R2Storage(client, "synthetic-bucket").put(raw, b"right")
        stub.add_response("get_object", {"Body": BytesIO(b"short"), "ContentLength": 99})
        with pytest.raises(EvidenceIntegrityError, match="length"):
            R2Storage(client, "synthetic-bucket").read(raw.object_path)


def test_r2_transport_failure_is_sanitized() -> None:
    class FailingClient:
        def get_object(self, **kwargs: object) -> object:
            raise EndpointConnectionError(endpoint_url="https://SYNTHETIC_SECRET.invalid")
    with pytest.raises(StorageAccessError) as error:
        R2Storage(FailingClient(), "synthetic-bucket").read("synthetic/object.bin")
    assert "SYNTHETIC_SECRET" not in "".join(traceback.format_exception(error.value))


@pytest.mark.parametrize("code", ["AccessDenied", "InternalError", "ConditionalRequestConflict"])
def test_r2_failed_write_never_attempts_a_read(code: str) -> None:
    client = make_client()
    with Stubber(client) as stub:
        stub.add_client_error("put_object", code, service_message="SYNTHETIC_SECRET")
        with pytest.raises(StorageAccessError) as error:
            R2Storage(client, "synthetic-bucket").put(raw_metadata(b"bytes"), b"bytes")
        assert "SYNTHETIC_SECRET" not in "".join(traceback.format_exception(error.value))
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("instant,expected", [
    (datetime(2026, 1, 15, 12, tzinfo=UTC), "20260115T120000000000Z"),
    (datetime(2026, 1, 15, 14, 30, 1, 123456,
              tzinfo=timezone(timedelta(hours=2, minutes=30))), "20260115T120001123456Z"),
    (datetime(1, 1, 1, tzinfo=UTC), "00010101T000000000000Z"),
])
def test_object_key_preserves_canonical_utc_timestamp(
    chain: EvidenceChain, instant: datetime, expected: str,
) -> None:
    source = Source.model_validate(chain.source.model_dump() | {"retrieved_at": instant})
    expected_key = (f"raw/v1/{source.company_number}/{source.source_type.value}/{expected}/"
                    f"{source.source_id}/{chain.raw.checksum}.xhtml")
    assert object_key(source, chain.raw.checksum, chain.raw.media_type) == expected_key
