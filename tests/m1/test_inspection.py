"""Acceptance example executes actual adapters and validates its printed evidence."""

import json
from pathlib import Path
import subprocess
import sys


def test_synthetic_storage_inspection_example() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / "examples" / "inspect_storage.py")],
                            cwd=root, capture_output=True, text=True, check=True, timeout=30)
    report = json.loads(result.stdout)
    assert "SYNTHETIC" in report["label"]
    assert report["company_round_trip"]["company_number"] == "ZZ000001"
    assert report["decimal"]["type"] == "Decimal"
    assert report["decimal"]["value"] == "12345.6700"
    assert report["decimal"]["tuple"][2] == -4
    assert report["missing"] == {"value": None, "status": "NOT_DISCLOSED", "sql_is_null": True}
    assert report["bytes_equal"] and report["immutable_overwrite_rejected"]
    assert report["lineage"][0]["checksum"] == report["sha256"]
    assert report["lineage"][0]["fact_id"] in report["reverse_evidence_to_fact_ids"]
