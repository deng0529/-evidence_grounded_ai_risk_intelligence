# M7 - Streamlit UI

## Objective

Implement the frozen MVP UI without moving business logic into
Streamlit.

## Pages

-   Search / Select / Analyse
-   Overview
-   Risk Detail
-   Evidence Explorer
-   Methodology

## Implement

-   Application-service calls from UI.
-   Controlled states: READY, LOADING, SUCCESS, PARTIAL, EMPTY,
    INVALID_INPUT, ERROR, NOT_IMPLEMENTED.
-   Overall/domain Low/High/Unknown display.
-   Deterministic key-risk-driver display.
-   Variable drill-down.
-   Evidence lineage drill-down.
-   Methodology/version display.
-   Friendly error handling; no raw traceback or secrets.

## Rules

-   Do not present High belief as probability of company failure.
-   Do not hide Unknown.
-   Do not use colour alone.
-   LLM explanation cannot alter results.

## Acceptance criteria

All interaction paths in the UI specification have a controlled
response.
