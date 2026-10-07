-- One current published display snapshot per company; source records stay immutable.
CREATE TABLE dashboard_snapshot (
    company_number TEXT PRIMARY KEY,
    m2_run_id TEXT NOT NULL REFERENCES processing_run(processing_run_id),
    m3_run_id TEXT NOT NULL REFERENCES processing_run(processing_run_id),
    config_fingerprint TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload TEXT NOT NULL CHECK(json_valid(payload))
) STRICT;
