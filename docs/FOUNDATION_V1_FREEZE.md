Historical freeze candidate. Superseded by implementation/FOUNDATION_FREEZE_20261003.md.

# Foundation v1 MVP freeze

## Scope
Foundation v1 demonstrates the evidence-grounded path for the three original demo companies only. Broad arbitrary-company format coverage is deferred.

## Data path
Companies House profile/filings/officers → immutable raw evidence in R2 → iXBRL or PDF/OCR extraction → OpenAI semantic fallback only for unresolved financial evidence → evidence admission → canonical normalization → structured Turso persistence/read-back → deterministic six-variable inputs.

## Canonical financial normalization
All admitted direct monetary facts pass through `financial-normalization-v1` before canonical persistence. Raw evidence and raw source labels/values remain unchanged. The normalization audit records source fact, raw value, normalized value, currency/unit, scale, version and rule.

Normalization is deliberately non-inferential: it does not invent missing concepts, periods, currencies or amounts. Parser-applied scale is not applied twice. Qualified parenthesized current liabilities are represented as positive obligations; net liabilities retain negative economic meaning; signed zero and already-supplied currency/unit casing are canonicalized.

## MVP acceptance
The third scanned/mixed-PDF demo company has completed A→E with all five financial inputs and all six variables available. Demo companies 1 and 2 must be rerun after the normalization change before tagging the freeze.

## Deferred backlog
Country Style Foods, HP Foods, arbitrary-company search, and broader filing-format coverage are not Foundation-v1 blockers. Unsupported future presentations should fail to explicit Unknown/reason rather than guess.

## Next stage
Do not reopen Foundation unless a regression affects the three-demo MVP. Next work is six-variable Low/Medium/High/Unknown belief transformation followed by Governance, Financial and Overall ER fusion. The UI must expose every intermediate transformation/fusion input, threshold/reference level, reliability/Unknown treatment, weight, belief distribution and output.
