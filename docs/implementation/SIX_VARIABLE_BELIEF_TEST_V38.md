# Saved-assessment upgrade repair — v38, 5 October 2026

V37 changed financial validation rules but reused legacy validated_fact IDs.
Immutable persistence consequently rejects changed validation results against
existing IDs. Empty-database tests failed to cover this upgrade scenario.

V38 uses a separate financial-subtotal-validation-v2 identity namespace and
passes the exact newly selected validated financial IDs to M5. This prevents
both immutable ID collisions and ambiguous mixing of old/new validation records.
Old records, raw source facts and R2 evidence remain unchanged. Workflow version
saved-foundation-leaf-test-v38 ensures failed/old leaf results are not replayed.
No Companies House, PDF processing, OpenAI or ER invocation is added.

The simplified UI, automatic company selection, two-decimal shares and approved
six-variable-reference-v1 standard remain unchanged. No cleanup command needed.

Stop Streamlit; unzip v38pkg into the existing project directory; run separately:
& ".\.venv\Scripts\python.exe" ".\v38pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
Select Six-variable belief test, then select a saved company.

Verification: 838 offline tests passed, including an upgrade from prior persisted
financial validation IDs, preservation of historical records, exact current
handoff selection, and repeat-result reuse. Installer/archive verified.
Live user Turso confirmation is pending; no credentials are available here.
