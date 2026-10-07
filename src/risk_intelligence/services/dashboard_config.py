"""One checked entry point for versioned risk, presentation and AI YAML settings."""
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
import yaml
from risk_intelligence.risk_variables.core import ACTIVE_VARIABLES, model_aggregation_config, RISK_MODEL_VERSION

CONFIG_PATH = Path(__file__).parent / 'config' / 'dashboard.yaml'

def load_dashboard_configuration() -> dict:
    """Read presentation settings, rejecting missing active variable metadata."""
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding='utf-8'))
    if not isinstance(raw, dict) or not raw.get('version') or not raw.get('title'):
        raise ValueError('Dashboard YAML configuration is incomplete')
    for code in ACTIVE_VARIABLES:
        metadata = raw.get('variables', {}).get(code, {})
        if not all(isinstance(metadata.get(key), str) and metadata[key] for key in
                   ('name', 'formula', 'reference_explanation', 'value_rule')):
            raise ValueError('Dashboard YAML lacks active variable metadata: ' + code)
    return raw

CONFIG = load_dashboard_configuration()
VARIABLE_NAMES = MappingProxyType({code: CONFIG['variables'][code]['name'] for code in ACTIVE_VARIABLES})

def configuration_fingerprint() -> str:
    """Invalidate published results when risk or presentation YAML changes."""
    risk_path = Path(__file__).parents[1] / 'risk_variables' / 'config' / 'risk_model.yaml'
    content = risk_path.read_text(encoding='utf-8') + '\n' + CONFIG_PATH.read_text(encoding='utf-8')
    return sha256(content.encode()).hexdigest()


def load_project_configuration(environ: dict[str, str]) -> dict:
    """Expose risk, UI and AI configuration through one application entry point."""
    from .model_config import load_model_configuration
    return {'risk_version': RISK_MODEL_VERSION, 'domains': model_aggregation_config(RISK_MODEL_VERSION),
            'dashboard': load_dashboard_configuration(), 'ai': load_model_configuration(environ)}
