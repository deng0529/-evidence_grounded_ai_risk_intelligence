# Streamlit Community Cloud deployment

1. Test V47 locally against the five retained companies.
2. After acceptance, commit/push the reviewed cumulative project to GitHub.
3. On Community Cloud create an app pointing to the reviewed repository,
   branch and streamlit_app.py. Select Python 3.12 in Advanced settings.
4. Paste the keys shown in .streamlit/secrets.example.toml into the hosting
   Secrets panel using real values. Use a Turso read-only token for viewing.
   Keep RISK_UI_PUBLIC="true". Never commit actual secrets or .env files.
5. Public viewing requires existing migrated structured tables, including the
   accepted reference stage tables. Apply upgrades locally with the existing
   maintenance process before deploying. The public dashboard never migrates.
6. Keep evidence storage set to local for this viewing-only UI: no R2 client
   is constructed and no evidence file is downloaded. No OpenAI or Companies
   House keys are needed for the public dashboard.
7. Confirm public sharing in the app settings, then test the app link in a
   signed-out browser with each retained company. Check pie labels, both
   domains, six variables and Unknown explanations.

The frontend exposes company-level saved values. It does not offer ingestion,
maintenance writes or secret display. Do not enable local maintenance mode on
an anonymous public deployment. Recheck results after future source refreshes.

Official documentation:
https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
