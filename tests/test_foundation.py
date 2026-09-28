"""Stable vocabulary, isolated settings and adapter-free boundary checks."""

import inspect
import json
import subprocess
import sys
from enum import StrEnum
from pathlib import Path
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from risk_intelligence import interfaces
from risk_intelligence.config import load_settings
from risk_intelligence.domain import enums


@pytest.mark.parametrize("enum_type,expected", [
    (enums.AvailabilityStatus, "AVAILABLE NOT_DISCLOSED NOT_APPLICABLE RETRIEVAL_FAILED EXTRACTION_FAILED VALIDATION_FAILED CONFLICT_UNRESOLVED NON_COMPARABLE"),
    (enums.ExtractionMethod, "API_DIRECT IXBRL_DIRECT PDF_NATIVE_DETERMINISTIC PDF_OCR_DETERMINISTIC LLM_NATIVE_TEXT LLM_OCR_TEXT DERIVED"),
    (enums.SourceType, "COMPANIES_HOUSE_API COMPANIES_HOUSE_IXBRL COMPANIES_HOUSE_PDF OFFICIAL_WEBSITE"),
    (enums.FactType, "NUMERIC DATE TEXT BOOLEAN CODES"),
    (enums.PeriodType, "INSTANT DURATION"),
    (enums.ComparabilityStatus, "COMPARABLE NON_COMPARABLE REVIEW_REQUIRED NOT_APPLICABLE"),
    (enums.AssessmentStatus, "COMPLETE PARTIAL FAILED"),
    (enums.ProcessingStatus, "PENDING RUNNING COMPLETE PARTIAL FAILED"),
    (enums.RetrievalStatus, "SUCCESS FAILED"),
    (enums.ValidationType, "SOURCE_CONSISTENCY PERIOD_CONSISTENCY CURRENCY_CONSISTENCY ARITHMETIC CROSS_SOURCE TEMPORAL DUPLICATE"),
    (enums.ValidationStatus, "PASS WARNING FAIL"),
    (enums.Severity, "INFO WARNING FAIL"),
    (enums.NodeType, "INDICATOR DOMAIN OVERALL"),
    (enums.TriggerType, "LIVE REFRESH DEMO_PRECOMPUTE"),
    (enums.FactRole, "REQUIRED SUPPORTING"),
])
def test_wire_vocabulary_is_exact(enum_type: type[StrEnum], expected: str) -> None:
    assert {member.value for member in enum_type} == set(expected.split())
    with pytest.raises(ValueError):
        enum_type("unrecognized-status")


def test_explicit_empty_settings_mapping_does_not_read_real_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RISK_ENVIRONMENT", "production")
    settings = load_settings({})
    assert settings.environment == "development"
    assert settings.local_data_directory == Path("data")
    assert settings.companies_house_api_key is None
    assert settings.openai_api_key is None


def test_settings_read_environment_only_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RISK_ENVIRONMENT", "test")
    monkeypatch.setenv("RISK_LOCAL_DATA_DIRECTORY", "data/synthetic")
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = load_settings()
    assert settings.environment == "test"
    assert settings.local_data_directory == Path("data/synthetic")


def test_test_only_credentials_are_excluded_from_serialization_and_repr() -> None:
    settings = load_settings({"COMPANIES_HOUSE_API_KEY": "SYNTHETIC_TEST_ONLY",
                              "OPENAI_API_KEY": "SYNTHETIC_TEST_ONLY"})
    assert "SYNTHETIC_TEST_ONLY" not in repr(settings)
    assert "SYNTHETIC_TEST_ONLY" not in settings.model_dump_json()
    assert "openai_api_key" not in settings.model_dump()
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "SYNTHETIC_TEST_ONLY"


def test_empty_credential_placeholders_are_absent() -> None:
    settings = load_settings({"COMPANIES_HOUSE_API_KEY": "", "OPENAI_API_KEY": ""})
    assert settings.companies_house_api_key is None
    assert settings.openai_api_key is None


def test_invalid_environment_fails_explicitly() -> None:
    with pytest.raises(ValidationError):
        load_settings({"RISK_ENVIRONMENT": "unknown"})


@pytest.mark.parametrize("protocol", [
    interfaces.CompanyRepository, interfaces.RecordRepository, interfaces.EvidenceStorage,
    interfaces.AssessmentRepository, interfaces.AssessmentService,
])
def test_interfaces_are_typed_contracts_without_concrete_adapters(protocol: type) -> None:
    with pytest.raises(TypeError, match="Protocols cannot be instantiated"):
        protocol()
    for name, method in inspect.getmembers(protocol, inspect.isfunction):
        if not name.startswith("_"):
            hints = get_type_hints(method)
            assert "return" in hints
            assert all(parameter == "self" or parameter in hints
                       for parameter in inspect.signature(method).parameters)
            assert inspect.getdoc(method)


def test_human_examples_execute_actual_contracts_offline() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "examples" / "inspect_contracts.py")],
        cwd=root, capture_output=True, text=True, check=True, timeout=15,
    )
    output = json.loads(result.stdout)
    assert output["unknown_string_rejected"] is True
    assert "SYNTHETIC" in output["label"]
    assert output["missing_fact"]["value_numeric"] is None
    assert output["valid_fact"]["value_numeric"] == "12345.6700"
    assert output["valid_fact"]["evidence_ids"] == [output["evidence"]["evidence_id"]]
    assert output["evidence"]["source_id"] == output["source"]["source_id"]
