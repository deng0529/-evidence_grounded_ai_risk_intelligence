"""Apply pending numbered migrations to the configured database, without printing secrets."""
from __future__ import annotations

import os
from pathlib import Path

from risk_intelligence.config import load_settings
from risk_intelligence.persistence.connection import open_database
from risk_intelligence.persistence.migrations import migrate


def environment(path: Path = Path('.env')) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                raise ValueError('Environment file must contain KEY=value entries')
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    values.update(os.environ)
    return values


def main() -> None:
    settings = load_settings(environment())
    with open_database(settings) as database:
        before = database.query('SELECT max(version) AS version FROM schema_migration') if database.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migration'") else [{'version': None}]
        migrate(database)
        after = database.query('SELECT max(version) AS version FROM schema_migration')
        print({'migration_version_before': before[0]['version'], 'migration_version_after': after[0]['version']})


if __name__ == '__main__':
    main()
