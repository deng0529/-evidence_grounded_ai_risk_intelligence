# M8 - Deployment, Caching and Public Demo

## Objective

Deploy a reproducible public MVP at minimal/free-tier cost.

## Target

-   GitHub: code/docs/tests
-   Streamlit Community Cloud: running Python application + UI
-   Turso: structured persistent data
-   Cloudflare R2: raw evidence
-   Companies House: live public source
-   OpenAI API: optional semantic extraction/explanation only

## Implement

-   Secrets configuration.
-   Production storage adapters.
-   Assessment cache keyed by company and validity/freshness policy.
-   Three precomputed reference-company demos.
-   Live UK company search path.
-   Partial assessment behavior.
-   Deployment smoke tests and README instructions.

## Acceptance criteria

A third party can open the public Streamlit URL, select/search a
company, receive a controlled assessment or partial/error state, and
trace displayed material results to evidence.
