"""Run with: python -m streamlit run streamlit_app.py.

Local development loads .env into process memory without printing secrets. Existing
OS environment variables take precedence.
"""
from pathlib import Path
import os


def _load_local_env(path: Path = Path('.env')) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


_load_local_env()
from risk_intelligence.ui.public_app import main

if __name__ == '__main__':
    main()
