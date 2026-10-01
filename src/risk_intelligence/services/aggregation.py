"""M6 registry-driven domain and overall ER aggregation service."""

from datetime import datetime
from decimal import Decimal, localcontext

from risk_intelligence.aggregation import WeightedBelief, aggregation_identity, er_aggregate
from risk_intelligence.domain.enums import NodeType
from risk_intelligence.domain.risk import AggregationInput, AggregationResult
from risk_intelligence.persistence.aggregation_repository import AggregationRepository
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.variable_repository import VariableRepository
from risk_intelligence.risk_variables.core import DECIMAL_CONTEXT, ER_MODEL_VERSION, RISK_MODEL_VERSION, model_aggregation_config


NODE_NAMES = {"GOVERNANCE": "Governance Risk", "FINANCIAL": "Financial Risk", "OVERALL": "Overall Company Risk"}


class AggregationService:
    """Consume persisted M5 leaves unchanged and persist reproducible M6 parents."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = AggregationRepository(database)

    @staticmethod
    def _result(assessment_id: str, node_code: str, node_type: NodeType, children: tuple[WeightedBelief, ...],
                *, version: str, calculated_at: datetime) -> tuple[AggregationResult, tuple[AggregationInput, ...]]:
        belief = er_aggregate(children)
        identity = aggregation_identity(assessment_id, node_code, version, children)
        result = AggregationResult(aggregation_result_id=identity, assessment_id=assessment_id,
            node_code=node_code, node_type=node_type, node_name=NODE_NAMES[node_code], belief=belief,
            er_model_version=version, calculated_at=calculated_at)
        edges = tuple(AggregationInput(aggregation_result_id=identity, child_code=item.code,
            child_result_id=item.result_id, importance_weight=item.weight) for item in children)
        return result, edges

    def calculate_and_persist(self, *, assessment_id: str, calculated_at: datetime) -> tuple[AggregationResult, ...]:
        context = SqlAssessmentRepository(self.database).get_assessment(assessment_id)
        if context is None:
            raise IntegrityError("M6 assessment is missing")
        if context.risk_model_version != RISK_MODEL_VERSION or context.er_model_version != ER_MODEL_VERSION:
            raise IntegrityError("M6 v1.2 requires matching risk/ER model version 1.2")
        config = model_aggregation_config(context.risk_model_version)
        leaves = {leaf.variable_code: leaf for leaf in VariableRepository(self.database).for_assessment(assessment_id)}
        domains: list[AggregationResult] = []
        with localcontext(DECIMAL_CONTEXT):
            for domain, spec in config.items():
                codes = spec["variables"]
                if spec["weighting_policy"] != "EQUAL_WEIGHT_ACTIVE_VARIABLES":
                    raise IntegrityError("Unsupported M6 within-domain weighting policy")
                weight = Decimal(1) / Decimal(len(codes))
                children = tuple(WeightedBelief(code=code, result_id=leaves[code].variable_result_id,
                    belief=leaves[code].final_belief, weight=weight) for code in codes)
                result, edges = self._result(assessment_id, domain, NodeType.DOMAIN, children,
                    version=context.er_model_version, calculated_at=calculated_at)
                self.repository.save(result, edges)
                domains.append(result)
            domain_by_code = {result.node_code: result for result in domains}
            top_children = tuple(WeightedBelief(code=domain, result_id=domain_by_code[domain].aggregation_result_id,
                belief=domain_by_code[domain].belief, weight=Decimal(spec["weight"])) for domain, spec in config.items())
            overall, edges = self._result(assessment_id, "OVERALL", NodeType.OVERALL, top_children,
                version=context.er_model_version, calculated_at=calculated_at)
            self.repository.save(overall, edges)
        return tuple(domains) + (overall,)
