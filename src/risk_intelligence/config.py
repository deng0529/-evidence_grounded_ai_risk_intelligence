"""Explicit environment loading with no file reads or external connections."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Settings(BaseModel):
    """Local application settings; credentials are optional and never validated remotely."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    environment: Literal["development", "test", "production"] = "development"
    local_data_directory: Path = Path("data")
    companies_house_api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    openai_api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Read supplied variables or os.environ without reading/writing a .env file.

    Passing a mapping makes tests independent of the developer's real secrets.
    Empty credential placeholders are treated as absent. No credentials are
    required at M0; service-specific storage credentials belong with M1 adapters.
    """
    values = os.environ if environ is None else environ
    return Settings.model_validate({
        "environment": values.get("RISK_ENVIRONMENT", "development"),
        "local_data_directory": Path(values.get("RISK_LOCAL_DATA_DIRECTORY", "data")),
        "companies_house_api_key": (
            SecretStr(values["COMPANIES_HOUSE_API_KEY"])
            if values.get("COMPANIES_HOUSE_API_KEY") else None
        ),
        "openai_api_key": (SecretStr(values["OPENAI_API_KEY"]) if values.get("OPENAI_API_KEY") else None),
    })
