"""Read-only M7 traceability assembly over persisted M4/M5/M6 records."""

from fractions import Fraction

from risk_intelligence.domain.runs import Assessment
from risk_intelligence.explanation import (
    AggregationExplanation, AssessmentExplanation, EvidenceExplanation,
    FinancialLineageExplanation, InputExplanation, VariableExplanation,
)
from risk_intelligence.persistence.accounts_repository import AccountsRepository
from risk_intelligence.persistence.aggregation_repository import AggregationRepository
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.evidence_repositories import (
    SqlDocumentRepository, SqlEvidenceReferenceRepository, SqlSourceRepository,
)
from risk_intelligence.persistence.fact_repositories import SqlFinancialFactRepository, SqlStructuredFactRepository
from risk_intelligence.persistence.validated_members import load_validated_members
from risk_intelligence.persistence.validated_repository import ValidatedEvidenceRepository
from risk_intelligence.persistence.variable_repository import VariableRepository
from risk_intelligence.risk_variables.core import LeafAssessment, ValidatedInput, model_aggregation_config, model_definitions
from risk_intelligence.validation.obligation_service import ObligationValidationService
from risk_intelligence.validation.governance_handoff import _snapshot_from_row

# Names from frozen risk-model-v1.2; labels do not control calculation or hierarchy.
VARIABLE_NAMES = {
    "G1.1": "Accounts Filing Lateness", "G1.2": "Confirmation Statement Lateness",
    "G2.2": "Median Active-Director Tenure", "F1.1": "Net Assets / Total Assets",
    "F2.2": "Current Ratio", "F2.3": "Quick Ratio",
}


def _required[T](value: T | None, description: str) -> T:
    if value is None:
        raise IntegrityError(f"M7 missing persisted {description}")
    return value


class ExplanationService:
    """Resolve an existing v1.2 assessment without calculation, writes or raw reads."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def _evidence(self, evidence_id: str, context: Assessment) -> EvidenceExplanation:
        reference = _required(SqlEvidenceReferenceRepository(self.database).get(evidence_id), "evidence reference")
        source = _required(SqlSourceRepository(self.database).get(reference.source_id), "source")
        document = (_required(SqlDocumentRepository(self.database).get(reference.document_id), "document")
                    if reference.document_id else None)
        if (source.company_id != context.company_id or source.company_number != context.company_number
                or (document is not None and (document.company_id != context.company_id
                    or document.company_number != context.company_number or document.source_id != source.source_id))):
            raise IntegrityError("M7 evidence company/source identity differs")
        return EvidenceExplanation(reference=reference, source=source, document=document)

    def _input(self, reference: ValidatedInput, context: Assessment) -> InputExplanation:
        repository = ValidatedEvidenceRepository(self.database)
        lineage = None
        if reference.kind == "FACT":
            record = _required(repository.get_fact(reference.validated_id), "validated fact")
            observations = (_required(SqlFinancialFactRepository(self.database).get(record.fact_id), "financial observation"),)
            saved_lineage = AccountsRepository(self.database).get_observation_lineage(record.fact_id)
            if saved_lineage is not None:
                metadata, components = saved_lineage
                lineage = FinancialLineageExplanation(**metadata, components=components)
            evidence_ids = set(record.evidence_ids) | set(record.validation_report.context.evidence_ids)
            reliability, ruleset, policy = record.reliability_r, record.validation_ruleset_version, record.reliability_policy_version
        elif reference.kind == "SET":
            members = load_validated_members(self.database, reference.validated_id)
            record, observations = members.validated, members.facts
            evidence_ids = set(record.validation_report.context.evidence_ids)
            reliability, ruleset, policy = record.reliability_r, record.validation_ruleset_version, record.reliability_policy_version
        else:
            record = _required(ObligationValidationService(self.database).get(reference.validated_id), "validated obligation")
            observations = tuple(_required(SqlStructuredFactRepository(self.database).get(fact_id), "obligation fact")
                                 for fact_id in record.fact_ids)
            evidence_ids = set(record.evidence_ids)
            reliability = record.assessment.calculation.reliability_r
            ruleset, policy = record.assessment.validation.ruleset_version, record.assessment.calculation.policy_version
        if (record.company_id != context.company_id or record.company_number != context.company_number
                or record.assessment_date > context.assessment_date
                or (reliability, ruleset, policy) != (reference.reliability_r, reference.validation_version, reference.reliability_version)):
            raise IntegrityError("M7 validated input identity/version/reliability differs")
        for observation in observations:
            if observation.company_id != context.company_id or observation.company_number != context.company_number:
                raise IntegrityError("M7 source observation company differs")
            evidence_ids.update(observation.evidence_ids)
        if lineage is not None:
            evidence_ids.update(component.evidence_id for component in lineage.components)
        # M4 governance evidence IDs include coverage snapshots as well as field
        # locators. Preserve those distinct types; a snapshot is not a JSON path.
        snapshots = {}
        snapshot_ids = (record.snapshot_ids if reference.kind == "SET" else
                        (record.profile_snapshot_id,) if reference.kind == "OBLIGATION" else ())
        pending = sorted(evidence_ids | set(snapshot_ids))
        locator_ids = []
        while pending:
            identity = pending.pop(0)
            rows = self.database.query("SELECT * FROM resource_snapshot WHERE snapshot_id=?", (identity,))
            if not rows:
                locator_ids.append(identity)
                continue
            snapshot = _snapshot_from_row(rows[0])
            if snapshot.company_id != context.company_id:
                raise IntegrityError("M7 snapshot company differs")
            if identity in snapshots:
                continue
            snapshots[identity] = snapshot
            if snapshot.reused_snapshot_id:
                pending.append(snapshot.reused_snapshot_id)
        return InputExplanation(reference=reference, record=record, observations=observations,
                                financial_lineage=lineage,
                                evidence=tuple(self._evidence(identity, context) for identity in sorted(set(locator_ids))),
                                snapshots=tuple(snapshots[key] for key in sorted(snapshots)))

    def _leaves(self, context: Assessment) -> dict[str, LeafAssessment]:
        repository = VariableRepository(self.database)
        rows = self.database.query(
            "SELECT variable_result_id FROM m5_variable_result WHERE assessment_id=? ORDER BY variable_code",
            (context.assessment_id,))
        leaves = tuple(_required(repository.get_persisted(str(row["variable_result_id"])), "M5 leaf") for row in rows)
        by_code = {leaf.result.variable_code: leaf for leaf in leaves}
        if len(by_code) != len(leaves) or set(by_code) != set(model_definitions(context.risk_model_version)):
            raise IntegrityError("M7 requires exactly the persisted active M5 leaves")
        for leaf in leaves:
            if (leaf.company_id != context.company_id or leaf.company_number != context.company_number
                    or leaf.assessment_date != context.assessment_date or leaf.result.assessment_id != context.assessment_id
                    or leaf.result.risk_model_version != context.risk_model_version
                    or leaf.result.reliability_model_version != context.reliability_model_version):
                raise IntegrityError("M7 M5 assessment identity/version differs")
        if len({leaf.analytical_scope for leaf in leaves}) != 1:
            raise IntegrityError("M7 M5 analytical scopes differ")
        return by_code

    def for_assessment(self, assessment_id: str) -> AssessmentExplanation:
        """Expose exact persisted results and lineage; fail on missing/broken required edges.

        Historical versions are explicitly unsupported here, rather than reinterpreted
        as v1.2. Optional absent source context remains None or an empty tuple.
        """
        assessments = SqlAssessmentRepository(self.database)
        context = _required(assessments.get_assessment(assessment_id), "assessment")
        if context.risk_model_version != "1.2" or context.er_model_version != "1.2":
            raise IntegrityError("M7 explanation supports risk/ER model v1.2 only")
        year = _required(assessments.get_financial_reporting_year(assessment_id), "financial reporting year")
        config = model_aggregation_config(context.risk_model_version)
        leaves = self._leaves(context)
        repository = AggregationRepository(self.database)
        results = repository.for_assessment(assessment_id)
        by_code = {result.node_code: result for result in results}
        if len(by_code) != len(results) or set(by_code) != {*config, "OVERALL"}:
            raise IntegrityError("M7 requires the persisted M6 domains and Overall")
        nodes = {}
        for code in (*config, "OVERALL"):
            result, edges = _required(repository.get(by_code[code].aggregation_result_id), "M6 result")
            expected_codes = tuple(config) if code == "OVERALL" else config[code]["variables"]
            if (result != by_code[code] or result.assessment_id != assessment_id
                    or result.er_model_version != context.er_model_version
                    or tuple(edge.child_code for edge in edges) != expected_codes):
                raise IntegrityError("M7 M6 hierarchy/version differs")
            for edge in edges:
                child_id = (by_code[edge.child_code].aggregation_result_id if code == "OVERALL"
                            else leaves[edge.child_code].result.variable_result_id)
                if edge.child_result_id != child_id:
                    raise IntegrityError("M7 M6 child result identity differs")
                if code == "OVERALL" and edge.importance_weight != config[edge.child_code]["weight"]:
                    raise IntegrityError("M7 M6 domain weight differs from frozen metadata")
            # Inspect stored weights only; never reconstruct or redistribute them.
            if abs(sum((Fraction(edge.importance_weight) for edge in edges), Fraction(0)) - 1) > Fraction(1, 100_000_000):
                raise IntegrityError("M7 M6 persisted child weights do not sum to one")
            if code != "OVERALL" and len({edge.importance_weight for edge in edges}) != 1:
                raise IntegrityError("M7 M6 domain children lack persisted equal weights")
            nodes[code] = AggregationExplanation(result=result, children=edges)
        variables = tuple(VariableExplanation(
            name=VARIABLE_NAMES[code], domain=domain,
            reporting_year=year if domain == "FINANCIAL" else None, leaf=leaves[code],
            inputs=tuple(self._input(reference, context) for reference in leaves[code].calculation.inputs),
        ) for domain, spec in config.items() for code in spec["variables"])
        return AssessmentExplanation(assessment=context, reporting_year=year, overall=nodes["OVERALL"],
                                     domains=tuple(nodes[domain] for domain in config), variables=variables)
