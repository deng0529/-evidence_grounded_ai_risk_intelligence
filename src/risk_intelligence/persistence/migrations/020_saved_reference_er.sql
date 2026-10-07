CREATE TABLE saved_reference_er (
 fingerprint TEXT PRIMARY KEY,
 calculation_id TEXT NOT NULL REFERENCES saved_reference_belief(calculation_id),
 method_version TEXT NOT NULL,
 payload TEXT NOT NULL CHECK(json_valid(payload))
) STRICT;
