# MVP Scope

## Objective
Demonstrate an end-to-end evidence-grounded company risk workflow using a small set of UK companies.

## MVP workflow
1. Enter/select a company.
2. Resolve its Companies House identity.
3. Retrieve selected public Companies House data.
4. Retrieve selected official website information.
5. Store raw source metadata.
6. Extract a limited set of structured facts.
7. Attach evidence to each material fact.
8. Validate the facts.
9. Calculate a small set of risk indicators.
10. Generate an evidence-grounded explanation.
11. Display the result in Streamlit.

## Initial company set
Use a small manually selected test set during development. Expand only after the pipeline is reliable.

## Initial output
For each company:
- identity/profile;
- selected financial indicators;
- selected governance indicators;
- selected resilience indicators;
- validation status;
- risk assessment;
- evidence trail.

## Out of scope
Large-scale automated monitoring, predictive default modelling, investment advice, regulated scoring, and enterprise deployment.
