"""Run an explicit, backed-up cleanup against the configured Turso and R2."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import os
import sys

root = Path.cwd()
sys.path.insert(0, str(root / 'src'))
for raw in (root / '.env').read_text(encoding='utf-8-sig').splitlines() if (root / '.env').is_file() else []:
    line = raw.strip()
    if line and not line.startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
from risk_intelligence.config import load_settings
from risk_intelligence.persistence.connection import open_database
from risk_intelligence.storage.r2 import R2Storage
from risk_intelligence.maintenance.retain_latest import cleanup

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply', action='store_true', help='Back up and remove old indexed records and objects')
args = parser.parse_args()
try:
    settings = load_settings()
    if settings.database_backend != 'turso' or settings.evidence_storage_backend != 'r2':
        raise ValueError('This command requires the project Turso and R2 configuration; local fallback is refused')
    folder = root / settings.local_data_directory / 'maintenance' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    with open_database(settings) as database:
        report = cleanup(database, R2Storage.from_settings(settings), folder, apply=args.apply)
    print('Retained latest companies: ' + ', '.join(report['pairs']))
    print('Old database rows: ' + str(sum(report['removed_rows'].values())))
    print('Old indexed objects: ' + str(report['old_objects']))
    if not args.apply:
        print('PLAN_ONLY: no data changed. Add --apply to execute.')
    else:
        print('Local backup: ' + str(folder))
        if report['pending_objects']:
            print('DATABASE_CLEANED_R2_PENDING: some old objects remain; see cleanup_report.json in the backup folder.')
            raise SystemExit(2)
        print('LATEST_FIVE_RETAINED: database and indexed R2 cleanup completed.')
except Exception as exc:
    print('CLEANUP_STOPPED: ' + type(exc).__name__)
    if isinstance(exc, ValueError):
        print(str(exc))
    print('No successful cleanup is claimed. Check configuration, connection and local backup reports.')
    raise SystemExit(1)
