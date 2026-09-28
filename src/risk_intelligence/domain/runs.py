"""Processing lifecycle and assessment metadata; no workflow execution."""

from datetime import date
from typing import Self

from pydantic import model_validator

from .common import CompanyNumber, Contract, Text, UtcTimestamp
from .enums import AssessmentStatus, ProcessingStatus, TriggerType


class ProcessingRun(Contract):
    """An auditable execution record with explicit, timezone-aware timestamps."""

    processing_run_id: Text
    company_id: Text
    company_number: CompanyNumber
    started_at: UtcTimestamp
    completed_at: UtcTimestamp | None = None
    status: ProcessingStatus
    current_stage: Text
    trigger_type: TriggerType
    app_version: Text
    error_code: Text | None = None
    error_message: Text | None = None

    @model_validator(mode="after")
    def check_timestamp_order(self) -> Self:
        """Reject impossible timestamp ordering; do not run a state machine."""
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        return self


class Assessment(Contract):
    """Versioned assessment identity; result values live in separate records."""

    assessment_id: Text
    company_id: Text
    company_number: CompanyNumber
    processing_run_id: Text
    assessment_date: date
    status: AssessmentStatus
    data_current_to: date | None = None
    risk_model_version: Text
    reliability_model_version: Text
    er_model_version: Text
    data_dictionary_version: Text
