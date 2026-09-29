-- M2 operational provenance only; no risk, reliability or financial extraction.
CREATE TABLE ingestion_run (
    processing_run_id TEXT PRIMARY KEY REFERENCES processing_run(processing_run_id),
    assessment_date TEXT NOT NULL,
    horizon_start TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    CHECK(horizon_start <= assessment_date)
) STRICT;
CREATE TABLE resource_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    processing_run_id TEXT NOT NULL REFERENCES ingestion_run(processing_run_id),
    company_id TEXT NOT NULL,
    resource TEXT NOT NULL CHECK(resource IN ('profile','officers','persons-with-significant-control',
        'persons-with-significant-control-statements','filing-history')),
    checked_at TEXT NOT NULL,
    coverage_start TEXT NOT NULL,
    coverage_end TEXT NOT NULL,
    complete INTEGER NOT NULL CHECK(complete IN (0,1)),
    availability_status TEXT NOT NULL CHECK(availability_status IN ('AVAILABLE','RETRIEVAL_FAILED','EXTRACTION_FAILED')),
    page_count INTEGER NOT NULL CHECK(page_count >= 0),
    item_count INTEGER NOT NULL CHECK(item_count >= 0),
    reused_snapshot_id TEXT REFERENCES resource_snapshot(snapshot_id),
    error_code TEXT,
    UNIQUE(processing_run_id,resource),
    FOREIGN KEY(processing_run_id,company_id) REFERENCES processing_run(processing_run_id,company_id),
    CHECK(coverage_start <= coverage_end),
    CHECK(complete=0 OR (availability_status='AVAILABLE' AND error_code IS NULL))
) STRICT;
CREATE INDEX snapshot_company_resource_time ON resource_snapshot(company_id,resource,checked_at);
CREATE TABLE api_response (
    source_id TEXT PRIMARY KEY REFERENCES raw_evidence(source_id),
    resource TEXT NOT NULL,
    request_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    etag TEXT,
    start_index INTEGER NOT NULL CHECK(start_index >= 0),
    requested_page_size INTEGER NOT NULL CHECK(requested_page_size >= 1)
) STRICT;
-- Search precedes canonical company selection. It must not fabricate a Company
-- or Source foreign key. The coordinator verifies these bytes before this row.
CREATE TABLE company_search_evidence (
    search_id TEXT PRIMARY KEY,
    request_path TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    http_status INTEGER NOT NULL CHECK(http_status=200),
    object_path TEXT NOT NULL,
    checksum TEXT NOT NULL CHECK(length(checksum)=64 AND checksum NOT GLOB '*[^0-9a-f]*'),
    content_type TEXT NOT NULL,
    etag TEXT
) STRICT;
CREATE TRIGGER snapshot_no_update BEFORE UPDATE ON resource_snapshot
BEGIN SELECT RAISE(ABORT,'immutable retrieval snapshot'); END;
CREATE TRIGGER snapshot_no_delete BEFORE DELETE ON resource_snapshot
BEGIN SELECT RAISE(ABORT,'immutable retrieval snapshot'); END;
CREATE TRIGGER ingestion_run_no_update BEFORE UPDATE ON ingestion_run
BEGIN SELECT RAISE(ABORT,'immutable ingestion context'); END;
CREATE TRIGGER ingestion_run_no_delete BEFORE DELETE ON ingestion_run
BEGIN SELECT RAISE(ABORT,'immutable ingestion context'); END;
CREATE TRIGGER api_response_no_update BEFORE UPDATE ON api_response
BEGIN SELECT RAISE(ABORT,'immutable response metadata'); END;
CREATE TRIGGER api_response_no_delete BEFORE DELETE ON api_response
BEGIN SELECT RAISE(ABORT,'immutable response metadata'); END;
CREATE TRIGGER search_evidence_no_update BEFORE UPDATE ON company_search_evidence
BEGIN SELECT RAISE(ABORT,'immutable search evidence'); END;
CREATE TRIGGER search_evidence_no_delete BEFORE DELETE ON company_search_evidence
BEGIN SELECT RAISE(ABORT,'immutable search evidence'); END;
