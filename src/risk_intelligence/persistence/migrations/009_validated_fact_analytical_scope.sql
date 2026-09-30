-- M4 Final Gate: preserve the explicit analytical scope validated by M4.
-- Existing pre-009 rows remain NULL rather than fabricating COMPANY/GROUP scope.
-- All new FinancialValidationService outputs supply the explicit scope.

ALTER TABLE validated_fact
ADD COLUMN analytical_scope TEXT
CHECK(
    analytical_scope IS NULL OR
    analytical_scope IN (
        'COMPANY',
        'GROUP',
        'UNRESOLVED',
        'UNSPECIFIED'
    )
);
