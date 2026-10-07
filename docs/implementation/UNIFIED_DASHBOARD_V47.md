# Unified risk explorer — V47, 6 October 2026

Authorized scope: integrate saved foundation, six-variable reference beliefs,
and hierarchical ER in a professional English UI. Cloud deployment is the
next acceptance step, not performed by this patch. No commit/push performed.

Default Risk dashboard: select company (empty placeholder until selection),
then Overview, Domain analysis, Variables & standards tabs. Overview uses
explicit-angle pie of overall ER and Governance/Financial table. Domain tab
shows each three-variable ER and explanation. Variables tab shows six values,
formulas, reference benchmarks, exact linear-transform explanations, Unknown
reasons and saved underlying inputs. No reliability or LLM-generated risk text.

Public viewing uses application_database read-only and persist=False reference
transformation. The same existing approved V42 memberships and V45 ER engine
are used; source values, anchors, weights and mathematical method are unchanged.
No migrations, source ingestion, provider calls or result writes from dashboard.
Existing local maintenance workflows remain in sidebar. RISK_UI_PUBLIC=true
hides all maintenance workflows in public hosting.

Verification: 895 tests passed before final sidebar-only adjustment; dashboard
checks repeated afterward. Tests compare entire database dumps before/after
selection and repeated viewing; no changes. Six leaves, both domains, chart,
no-selection placeholder, tabs and public maintenance isolation are checked.
No live five-company/Turso/R2 access; user acceptance and hosting pending.

Deploy with Python 3.12, entry streamlit_app.py, requirements.txt installing
this repository, and server-side Streamlit Secrets. Read deployment guide.
