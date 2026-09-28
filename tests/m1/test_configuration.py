"""Explicit backend selection, secret redaction and provider construction."""

from pathlib import Path
import traceback

import pytest
from pydantic import ValidationError

from risk_intelligence.config import load_settings
from risk_intelligence.persistence.connection import open_database, PersistenceError
from risk_intelligence.storage.r2 import R2Storage


def cloud_config() -> dict[str, str]:
    return {"RISK_ENVIRONMENT": "production", "RISK_DATABASE_BACKEND": "turso",
            "RISK_EVIDENCE_STORAGE_BACKEND": "r2", "TURSO_DATABASE_URL": "libsql://synthetic.invalid",
            "TURSO_AUTH_TOKEN": "SYNTHETIC_TURSO_SECRET", "R2_ACCOUNT_ID": "0" * 32,
            "R2_BUCKET_NAME": "synthetic-test", "R2_ACCESS_KEY_ID": "SYNTHETIC_R2_KEY",
            "R2_SECRET_ACCESS_KEY": "SYNTHETIC_R2_SECRET"}


def test_local_defaults_do_not_connect_or_create_files(tmp_path: Path) -> None:
    directory = tmp_path / "not-created"
    settings = load_settings({"RISK_LOCAL_DATA_DIRECTORY": str(directory)})
    assert settings.database_backend == "sqlite"
    assert settings.evidence_storage_backend == "local"
    assert not directory.exists()
    with open_database(settings) as database:
        assert database.query("SELECT name FROM sqlite_master WHERE type='table'") == []
    assert (directory / "metadata.sqlite3").exists()


@pytest.mark.parametrize("missing", ["TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "R2_ACCOUNT_ID", "R2_BUCKET_NAME",
                                      "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"])
def test_cloud_configuration_missing_values_never_falls_back(missing: str) -> None:
    values = cloud_config()
    del values[missing]
    with pytest.raises(ValidationError):
        load_settings(values)


def test_production_requires_both_cloud_backends() -> None:
    with pytest.raises(ValidationError, match="production requires"):
        load_settings({"RISK_ENVIRONMENT": "production"})


def test_secrets_hidden_from_settings_and_validation_errors() -> None:
    values = cloud_config()
    settings = load_settings(values)
    rendered = repr(settings) + settings.model_dump_json()
    for key in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        assert values[key] not in rendered
    with pytest.raises(ValidationError) as error:
        load_settings(values | {"R2_ACCOUNT_ID": "invalid"})
    assert "SYNTHETIC_R2_SECRET" not in str(error.value)


def test_turso_open_uses_pinned_api_without_replication(monkeypatch: pytest.MonkeyPatch) -> None:
    import libsql
    import sqlite3
    captured: dict[str, object] = {}
    def connect(database: str, **kwargs: object) -> object:
        captured.update(database=database, **kwargs)
        return sqlite3.connect(":memory:", isolation_level=None)
    monkeypatch.setattr(libsql, "connect", connect)
    with open_database(load_settings(cloud_config())) as database:
        assert database.query("PRAGMA foreign_keys") == [{"foreign_keys": 1}]
    assert captured == {"database": "libsql://synthetic.invalid", "auth_token": "SYNTHETIC_TURSO_SECRET",
                        "isolation_level": None}


def test_turso_connect_failure_does_not_expose_provider_message(monkeypatch: pytest.MonkeyPatch) -> None:
    import libsql
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("SYNTHETIC_TURSO_SECRET")
    monkeypatch.setattr(libsql, "connect", fail)
    with pytest.raises(PersistenceError) as error:
        open_database(load_settings(cloud_config()))
    assert "SYNTHETIC_TURSO_SECRET" not in "".join(traceback.format_exception(error.value))


def test_r2_client_uses_explicit_credentials_endpoint_and_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    import boto3
    captured: dict[str, object] = {}
    def client(service: str, **kwargs: object) -> object:
        assert service == "s3"
        captured.update(kwargs)
        return object()
    monkeypatch.setattr(boto3, "client", client)
    R2Storage.from_settings(load_settings(cloud_config()))
    assert captured["endpoint_url"] == "https://" + "0" * 32 + ".r2.cloudflarestorage.com"
    assert captured["aws_secret_access_key"] == "SYNTHETIC_R2_SECRET"
    assert captured["config"].retries == {"total_max_attempts": 1}
