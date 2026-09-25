# Evidence Model

## Purpose
Define how the system proves where a material fact came from.

## Candidate evidence fields
- evidence_id
- source_id
- document_id
- source_type
- source_name
- source_url
- retrieved_at
- document_title
- document_date
- location_type
- location_value
- evidence_text
- extraction_method
- validation_status
- confidence
- notes

## Principle
A user should be able to start from a risk finding and navigate backwards to the exact supporting evidence.

## Handling uncertainty
If evidence is missing, ambiguous, conflicting, or inaccessible, the system should expose that status rather than fabricate certainty.

## Validation
Validation may combine:
- schema/type checks;
- source consistency checks;
- arithmetic checks;
- duplicate/cross-source comparison;
- evidence-location checks;
- LLM-assisted semantic checks.

The final validation status must remain distinguishable from an LLM confidence score.
