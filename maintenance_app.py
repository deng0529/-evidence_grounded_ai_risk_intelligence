"""Independent maintenance UI. Run locally; never use as the public entry point."""
from streamlit_app import _load_local_env
from risk_intelligence.ui.streamlit_app import main

_load_local_env()
if __name__ == '__main__':
    main()
