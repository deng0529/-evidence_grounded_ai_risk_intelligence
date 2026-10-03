"""Versioned, secret-free model and download configuration loaded only for live work."""
from pathlib import Path
from collections.abc import Mapping
import re
import yaml
from pydantic import BaseModel, ConfigDict


class RuntimeConfigurationError(ValueError):
    """A server-side model, credential or download setting needs attention."""


class ModelConfiguration(BaseModel):
    """Explicit model names and exact download hosts, never credentials."""
    model_config = ConfigDict(extra='forbid', frozen=True)
    version: str
    extraction_model: str
    explanation_model: str
    download_hosts: tuple[str, ...] = ()


def load_model_configuration(environ: Mapping[str, str]) -> ModelConfiguration:
    """Load packaged YAML or an explicit administrator file; reject unsafe hosts."""
    path = Path(environ.get('RISK_MODEL_CONFIG_PATH', str(Path(__file__).parent / 'config' / 'models.yaml')))
    try:
        result = ModelConfiguration.model_validate(yaml.safe_load(path.read_text(encoding='utf-8')))
        if not result.version.strip() or not result.extraction_model.strip() or not result.explanation_model.strip():
            raise ValueError('Empty model setting')
        if any(not re.fullmatch(r'[a-z0-9.-]+', host) for host in result.download_hosts):
            raise ValueError('Invalid download host')
        return result
    except (OSError, ValueError, yaml.YAMLError):
        raise RuntimeConfigurationError('Model/download configuration is invalid') from None
