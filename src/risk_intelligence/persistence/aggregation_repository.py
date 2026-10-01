"""Immutable M6 parent beliefs and exact weighted-child audit edges."""

from decimal import Decimal

from risk_intelligence.domain.risk import AggregationInput, AggregationResult
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.records import insert_immutable


class AggregationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _edge_row(edge: AggregationInput, position: int) -> dict:
        return {"aggregation_result_id": edge.aggregation_result_id, "position": position,
                "child_code": edge.child_code, "child_result_id": edge.child_result_id,
                "importance_weight": str(edge.importance_weight)}

    def save(self, result: AggregationResult, inputs: tuple[AggregationInput, ...]) -> None:
        result = AggregationResult.model_validate(result)
        inputs = tuple(AggregationInput.model_validate(item) for item in inputs)
        if not inputs or any(item.aggregation_result_id != result.aggregation_result_id for item in inputs):
            raise IntegrityError("M6 aggregation inputs do not belong to result")
        if len({item.child_code for item in inputs}) != len(inputs):
            raise IntegrityError("M6 aggregation child codes must be unique")
        if abs(sum((Decimal(item.importance_weight) for item in inputs), Decimal(0)) - Decimal(1)) > Decimal("1e-8"):
            raise IntegrityError("M6 aggregation importance weights must sum to one")
        row = {"aggregation_result_id": result.aggregation_result_id, "assessment_id": result.assessment_id,
               "node_code": result.node_code, "node_type": result.node_type.value,
               "er_model_version": result.er_model_version,
               "low_belief": str(result.belief.low_belief), "high_belief": str(result.belief.high_belief),
               "unknown_belief": str(result.belief.unknown_belief), "record_json": result.model_dump_json()}
        with self.database.transaction():
            if insert_immutable(self.database, "m6_aggregation_result", "aggregation_result_id", row):
                for position, edge in enumerate(inputs):
                    values = self._edge_row(edge, position)
                    self.database.execute("INSERT INTO m6_aggregation_input VALUES (?,?,?,?,?)", tuple(values.values()))
            else:
                existing = self.get(result.aggregation_result_id)
                if existing != (result, inputs):
                    raise IntegrityError("M6 immutable retry differs from persisted result")

    def get(self, aggregation_result_id: str) -> tuple[AggregationResult, tuple[AggregationInput, ...]] | None:
        rows = self.database.query("SELECT * FROM m6_aggregation_result WHERE aggregation_result_id=?", (aggregation_result_id,))
        if not rows:
            return None
        result = AggregationResult.model_validate_json(str(rows[0]["record_json"]))
        edge_rows = self.database.query("SELECT * FROM m6_aggregation_input WHERE aggregation_result_id=? ORDER BY position", (aggregation_result_id,))
        inputs = tuple(AggregationInput(aggregation_result_id=aggregation_result_id,
            child_code=row["child_code"], child_result_id=str(row["child_result_id"]),
            importance_weight=Decimal(str(row["importance_weight"]))) for row in edge_rows)
        return result, inputs

    def for_assessment(self, assessment_id: str) -> tuple[AggregationResult, ...]:
        rows = self.database.query("SELECT record_json FROM m6_aggregation_result WHERE assessment_id=? ORDER BY node_code", (assessment_id,))
        return tuple(AggregationResult.model_validate_json(str(row["record_json"])) for row in rows)
