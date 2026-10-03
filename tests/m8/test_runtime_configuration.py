"""Server settings remain secret-free and runtime wiring preserves host policy."""
from pydantic import SecretStr
import pytest
from risk_intelligence.config import Settings
from risk_intelligence.services.model_config import load_model_configuration, RuntimeConfigurationError
from risk_intelligence.services.application import error_message


def test_packaged_yaml_has_models_but_no_credentials():
    config = load_model_configuration({})
    assert config.extraction_model == 'gpt-5-mini'
    assert config.explanation_model == 'gpt-5-mini'
    assert config.download_hosts == ('s3.eu-west-2.amazonaws.com',)
    assert 'key' not in config.model_dump()


def test_yaml_host_reaches_document_client(database, tmp_path):
    from risk_intelligence.services.application_runtime import ingestion_services
    path = tmp_path / 'models.yaml'
    path.write_text('version: test-v1\nextraction_model: test-extraction\nexplanation_model: test-explanation\ndownload_hosts: [objects.example.invalid]\n')
    settings = Settings(companies_house_api_key=SecretStr('synthetic'), local_data_directory=tmp_path)
    _, accounts = ingestion_services(database, settings, {'RISK_MODEL_CONFIG_PATH': str(path)}, enable_llm=True)
    assert accounts.client.download_hosts == ('objects.example.invalid',)
    assert accounts.llm is None  # Deterministic processing remains possible without an optional key.


def test_bad_configuration_is_distinct_from_invalid_user_input(tmp_path):
    path = tmp_path / 'bad.yaml'; path.write_text('version: secret\ndownload_hosts: ["*.example.invalid"]')
    with pytest.raises(RuntimeConfigurationError) as ctx:
        load_model_configuration({'RISK_MODEL_CONFIG_PATH': str(path)})
    message = error_message(ctx.value)
    assert message.code == 'CONFIGURATION'
    assert str(path) not in message.message
