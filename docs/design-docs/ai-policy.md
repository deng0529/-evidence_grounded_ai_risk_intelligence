# AI Usage Policy

## Principle
AI assists the system; it does not become the source of truth.

## Appropriate uses
- semantic document understanding;
- extraction into a predefined schema;
- classification;
- evidence relevance assessment;
- natural-language explanation;
- summarisation of already validated facts.

## Restricted uses
An LLM should not:
- invent missing values;
- silently correct source data;
- make an unsupported factual assertion;
- overwrite validated facts without an explicit validation process;
- determine a material risk score without a documented methodology.

## Structured output
Where LLM extraction is used, prefer schema-constrained structured output and validate it with application code.

## Prompt/version traceability
Important extraction or explanation prompts should be versioned or otherwise identifiable so results can be investigated.

## Human review
The MVP should make it possible for a human reviewer to inspect important evidence and challenge a result.
