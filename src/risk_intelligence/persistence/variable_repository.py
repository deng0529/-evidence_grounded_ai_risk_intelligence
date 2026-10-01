"""Append-only M5 results and relational links to the exact M4 inputs consumed."""

from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.records import insert_immutable
from risk_intelligence.persistence.validated_repository import ValidatedEvidenceRepository
from risk_intelligence.risk_variables.core import model_definitions, LeafAssessment, make_leaf
from risk_intelligence.domain.risk import VariableResult
from risk_intelligence.validation.obligation_service import ObligationValidationService


class VariableRepository:
    """Persist supplied calculations after identity, upstream provenance and belief checks."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def _check(self, leaf: LeafAssessment) -> None:
        result = leaf.result
        context = SqlAssessmentRepository(self.database).get_assessment(result.assessment_id)
        if (context is None or context.company_id != leaf.company_id or context.company_number != leaf.company_number
                or context.assessment_date != leaf.assessment_date or context.risk_model_version != result.risk_model_version
                or context.reliability_model_version != result.reliability_model_version):
            raise IntegrityError("M5 assessment identity/version mismatch")
        reproduced = make_leaf(code=result.variable_code, calculation=leaf.calculation,
                               assessment_id=result.assessment_id, company_id=leaf.company_id,
                               company_number=leaf.company_number, assessment_date=leaf.assessment_date,
                               scope=leaf.analytical_scope, calculated_at=result.calculated_at,
                               model_version=result.risk_model_version)
        if reproduced != leaf:
            raise IntegrityError("M5 leaf beliefs or identity do not reproduce")
        repository = ValidatedEvidenceRepository(self.database)
        for link in leaf.calculation.inputs:
            if link.kind == "OBLIGATION":
                record = ObligationValidationService(self.database).get(link.validated_id)
                if record is None:
                    raise IntegrityError("M5 obligation input is missing")
                reliability = record.assessment.calculation.reliability_r
                validation_version = record.assessment.validation.ruleset_version
                reliability_version = record.assessment.calculation.policy_version
            else:
                record = (repository.get_fact(link.validated_id) if link.kind == "FACT"
                          else repository.get_evidence_set(link.validated_id))
                if record is None:
                    raise IntegrityError("M5 validated input is missing")
                reliability = record.reliability_r
                validation_version = record.validation_ruleset_version
                reliability_version = record.reliability_policy_version
            if (record.company_id != leaf.company_id or record.company_number != leaf.company_number
                    or record.assessment_date > leaf.assessment_date or reliability != link.reliability_r
                    or validation_version != link.validation_version or reliability_version != link.reliability_version):
                raise IntegrityError("M5 upstream identity/reliability/version mismatch")

    @staticmethod
    def _links(leaf: LeafAssessment) -> list[dict]:
        return [{"variable_result_id": leaf.result.variable_result_id, "position": index,
                 "validated_fact_id": item.validated_id if item.kind == "FACT" else None,
                 "validated_evidence_set_id": item.validated_id if item.kind == "SET" else None,
                 "validated_obligation_id": item.validated_id if item.kind == "OBLIGATION" else None,
                 "mandatory": int(item.mandatory)} for index, item in enumerate(leaf.calculation.inputs)]

    def save(self, leaf: LeafAssessment) -> None:
        """Verify upstream references and atomically append the leaf and ordered lineage."""
        leaf = LeafAssessment.model_validate(leaf)
        with self.database.transaction():
            self._check(leaf)
            result = leaf.result
            row = {"variable_result_id": result.variable_result_id, "assessment_id": result.assessment_id,
                   "variable_code": result.variable_code, "reliability_id": result.reliability_id,
                   "raw_value": str(result.raw_value) if result.raw_value is not None else None,
                   "reliability_r": str(result.reliability_r),
                   "low_belief": str(result.final_belief.low_belief),
                   "high_belief": str(result.final_belief.high_belief),
                   "unknown_belief": str(result.final_belief.unknown_belief),
                   "calculation_version": leaf.calculation_version, "record_json": leaf.model_dump_json()}
            if insert_immutable(self.database, "m5_variable_result", "variable_result_id", row):
                for link in self._links(leaf):
                    self.database.execute("INSERT INTO m5_validated_input VALUES (?,?,?,?,?,?)", tuple(link.values()))
            else:
                self.get(result.variable_result_id)

    def get(self, variable_result_id: str) -> LeafAssessment | None:
        """Restore frozen leaf and verify lineage; never execute a new source selection."""
        rows = self.database.query("SELECT * FROM m5_variable_result WHERE variable_result_id=?", (variable_result_id,))
        if not rows:
            return None
        leaf = LeafAssessment.model_validate_json(str(rows[0]["record_json"]))
        links = self.database.query("SELECT * FROM m5_validated_input WHERE variable_result_id=? ORDER BY position", (variable_result_id,))
        if leaf.result.variable_result_id != variable_result_id or links != self._links(leaf):
            raise IntegrityError("M5 persisted identity/lineage differs")
        self._check(leaf)
        return leaf

    def for_assessment(self, assessment_id: str) -> tuple[VariableResult, ...]:
        """M6 handoff: all active model leaves unchanged, with no aggregation or discount."""
        rows = self.database.query("SELECT variable_result_id FROM m5_variable_result WHERE assessment_id=? ORDER BY variable_code", (assessment_id,))
        leaves = tuple(self.get(str(row["variable_result_id"])) for row in rows)
        context = SqlAssessmentRepository(self.database).get_assessment(assessment_id)
        if context is None:
            raise IntegrityError("M5 assessment is missing")
        if len(leaves) != len(model_definitions(context.risk_model_version)) or {leaf.result.variable_code for leaf in leaves} != set(model_definitions(context.risk_model_version)):
            raise IntegrityError("M6 handoff requires exactly all active model leaves")
        if len({leaf.analytical_scope for leaf in leaves}) != 1:
            raise IntegrityError("M6 handoff mixes analytical scopes")
        return tuple(leaf.result for leaf in leaves)
