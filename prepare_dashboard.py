"""Prepare published dashboard results from existing structured sources only."""
import os
from streamlit_app import _load_local_env
from risk_intelligence.services.application_runtime import application_database
from risk_intelligence.services.dashboard_snapshot import prepare_all_dashboard_snapshots
from risk_intelligence.services.dashboard_config import load_project_configuration


def main() -> int:
    """Use the local maintenance credentials; print progress without secrets."""
    _load_local_env()
    print('Preparing saved dashboard results; no ingestion or OpenAI calls.',flush=True)
    try:
        load_project_configuration(dict(os.environ))
        with application_database(dict(os.environ),write=True) as database:
            numbers=prepare_all_dashboard_snapshots(database)
    except Exception:
        print('Preparation could not finish. Check database access and the saved source records. No dashboard result batch was published.',flush=True)
        return 1
    if not numbers:
        print('No saved companies were found. No results were generated.',flush=True)
        return 1
    print('DASHBOARD_RESULTS_READY: '+', '.join(numbers),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
