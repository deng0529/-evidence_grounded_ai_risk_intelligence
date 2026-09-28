"""Explicit environment loading with no file reads or external connections."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Self
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class Settings(BaseModel):
    """Explicit backend configuration; validate locally without remote side effects."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    environment: Literal["development", "test", "production"] = "development"
    local_data_directory: Path = Path("data")
    database_backend: Literal["sqlite", "turso"] = "sqlite"
    evidence_storage_backend: Literal["local", "r2"] = "local"
    turso_database_url: SecretStr | None = Field(default=None, exclude=True, repr=False)
    turso_auth_token: SecretStr | None = Field(default=None, exclude=True, repr=False)
    r2_account_id: str | None = None
    r2_bucket_name: str | None = None
    r2_access_key_id: SecretStr | None = Field(default=None, exclude=True, repr=False)
    r2_secret_access_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    companies_house_api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    openai_api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def validate_storage_configuration(self) -> Self:
        """Require selected cloud credentials and prevent production local fallback."""
        if self.environment == "production" and (
            self.database_backend != "turso" or self.evidence_storage_backend != "r2"
        ):
            raise ValueError("production requires turso and r2 storage backends")
        if self.database_backend == "turso":
            if not self.turso_database_url or not self.turso_auth_token:
                raise ValueError("Turso requires TURSO_DATABASE_URL and TURSO_AUTH_TOKEN")
            parsed = urlsplit(self.turso_database_url.get_secret_value())
            if (parsed.scheme not in ("libsql", "https") or not parsed.hostname
                    or parsed.username or parsed.password or parsed.query or parsed.fragment):
                raise ValueError("Turso requires a secure database URL without embedded credentials")
        if self.evidence_storage_backend == "r2":
            if not all((self.r2_account_id, self.r2_bucket_name, self.r2_access_key_id, self.r2_secret_access_key)):
                raise ValueError("R2 requires account, bucket, access key and secret key")
            if not re.fullmatch(r"[a-f0-9]{32}", self.r2_account_id or ""):
                raise ValueError("R2 account ID must contain 32 lowercase hexadecimal characters")
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.r2_bucket_name or ""):
                raise ValueError("R2 bucket name is invalid")
        return self


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Read supplied variables or os.environ without reading/writing a .env file.

    Passing a mapping makes tests independent of the developer's real secrets.
    Empty placeholders are absent. Local defaults need no credentials; selecting
    a cloud backend requires its explicit configuration, never credential discovery.
    """
    values = os.environ if environ is None else environ
    return Settings.model_validate({
        "environment": values.get("RISK_ENVIRONMENT", "development"),
        "local_data_directory": Path(values.get("RISK_LOCAL_DATA_DIRECTORY", "data")),
        "database_backend": values.get("RISK_DATABASE_BACKEND", "sqlite"),
        "evidence_storage_backend": values.get("RISK_EVIDENCE_STORAGE_BACKEND", "local"),
        "turso_database_url": SecretStr(values["TURSO_DATABASE_URL"]) if values.get("TURSO_DATABASE_URL") else None,
        "turso_auth_token": SecretStr(values["TURSO_AUTH_TOKEN"]) if values.get("TURSO_AUTH_TOKEN") else None,
        "r2_account_id": values.get("R2_ACCOUNT_ID") or None,
        "r2_bucket_name": values.get("R2_BUCKET_NAME") or None,
        "r2_access_key_id": SecretStr(values["R2_ACCESS_KEY_ID"]) if values.get("R2_ACCESS_KEY_ID") else None,
        "r2_secret_access_key": SecretStr(values["R2_SECRET_ACCESS_KEY"]) if values.get("R2_SECRET_ACCESS_KEY") else None,
        "companies_house_api_key": (
            SecretStr(values["COMPANIES_HOUSE_API_KEY"])
            if values.get("COMPANIES_HOUSE_API_KEY") else None
        ),
        "openai_api_key": (SecretStr(values["OPENAI_API_KEY"]) if values.get("OPENAI_API_KEY") else None),
    })
