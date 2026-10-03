"""Retain each pilot's latest Foundation pair; remove only unreferenced history."""
from collections import defaultdict
from pathlib import Path
import json
import re
import sqlite3

from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.migrations import MIGRATIONS_DIRECTORY
from risk_intelligence.services.data_foundation import load_foundation, latest_saved_run
from risk_intelligence.storage.objects import verify_checksum, validate_object_path

COMPANIES = ('05127466', 'SC137690', '08624397', '02554051', '02251694')
RID = '__maintenance_rowid'


def identifier(name: str) -> str:
    """Quote only schema identifiers, never user-controlled SQL fragments."""
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise IntegrityError('Unsupported schema identifier')
    return '"' + name + '"'


def snapshot(database: Database) -> dict:
    """Capture schema and all project rows without connection settings or tokens."""
    schema = database.query("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL "
                            "AND name NOT LIKE 'sqlite_%' ORDER BY type,name")
    tables = [str(r['name']) for r in schema if r['type']=='table']
    expected = {'schema_migration'}
    for file in MIGRATIONS_DIRECTORY.glob('*.sql'):
        expected.update(re.findall(r'CREATE TABLE\s+(\w+)', file.read_text(), re.I))
    if set(tables) - expected:
        raise IntegrityError('Unrecognized tables; no cleanup is allowed')
    rows, foreign, columns = {}, {}, {}
    for name in tables:
        table = identifier(name)
        columns[name] = database.query(f'PRAGMA table_info({table})')
        if any(c['name']==RID for c in columns[name]):
            raise IntegrityError('Reserved maintenance column exists')
        rows[name] = database.query(f'SELECT rowid AS {RID}, * FROM {table} ORDER BY rowid')
        foreign[name] = database.query(f'PRAGMA foreign_key_list({table})')
    if database.query('PRAGMA foreign_key_check'):
        raise IntegrityError('Existing foreign-key errors; no cleanup is allowed')
    return {'schema':schema,'rows':rows,'foreign':foreign,'columns':columns}


def plan(database: Database, saved: dict) -> dict:
    """Keep latest pairs and their complete dependency graph; refuse older-run reuse."""
    pairs = {}
    for number in COMPANIES:
        pair = latest_saved_run(database, number)
        if pair is None:
            raise IntegrityError(f'No latest saved Foundation pair for {number}; nothing removed')
        view = load_foundation(database, *pair)
        if len(view.facts)!=5:
            raise IntegrityError('Latest financial inputs are incomplete; nothing removed')
        pairs[number] = list(pair)
    runs = {run for pair in pairs.values() for run in pair}
    rows = saved['rows']
    nodes = {(table,row[RID]):row for table, items in rows.items() for row in items}
    links = defaultdict(set)
    children = defaultdict(set)
    indexes = {}
    for table, fks in saved['foreign'].items():
        groups = defaultdict(list)
        for fk in fks: groups[fk['id']].append(fk)
        for group in groups.values():
            group.sort(key=lambda f:f['seq'])
            parent = group[0]['table']
            target = tuple(f['to'] for f in group)
            if any(c is None for c in target):
                target = tuple(c['name'] for c in sorted(saved['columns'][parent],key=lambda c:c['pk']) if c['pk'])
            index_key = (parent,target)
            if index_key not in indexes:
                indexes[index_key] = {tuple(row[c] for c in target):(parent,row[RID]) for row in rows[parent]}
            for row in rows[table]:
                values = tuple(row[f['from']] for f in group)
                if any(v is None for v in values): continue
                parent_node = indexes[index_key].get(values)
                if parent_node is None: raise IntegrityError('Dependency absent; nothing removed')
                node = (table,row[RID])
                links[node].add(parent_node); children[parent_node].add(node)
    kept = {node for node,row in nodes.items() if row.get('processing_run_id') in runs or node[0]=='schema_migration'}
    queue = list(kept)
    while queue:
        node = queue.pop()
        additions = set(links[node])
        # Owned detail tables without run IDs are retained through their parent.
        # Company -> historic processing runs must never expand the keep set.
        if node[0] != 'company':
            additions.update(child for child in children[node] if 'processing_run_id' not in nodes[child])
        for addition in additions - kept:
            kept.add(addition); queue.append(addition)
    actual_runs = {nodes[node]['processing_run_id'] for node in kept if node[0]=='processing_run'}
    if actual_runs != runs:
        raise IntegrityError('Latest results reuse older-run evidence; cleanup refused rather than losing provenance')
    removed = {table:[row[RID] for row in items if (table,row[RID]) not in kept] for table,items in rows.items()}
    kept_paths = {row['object_path'] for row in rows.get('raw_evidence',[]) if ('raw_evidence',row[RID]) in kept}
    objects = {row['object_path']:row['checksum'] for row in rows.get('raw_evidence',[])
               if ('raw_evidence',row[RID]) not in kept and row['object_path'] not in kept_paths}
    objects.update({row['object_path']:row['checksum'] for row in rows.get('company_search_evidence',[])
                    if ('company_search_evidence',row[RID]) not in kept and row['object_path'] not in kept_paths})
    return {'pairs':pairs,'removed':removed,'objects':objects}


def backup_database(saved: dict, path: Path) -> None:
    """Write a restorable SQLite snapshot with original schema/triggers and public data."""
    with sqlite3.connect(path) as db:
        for item in saved['schema']:
            if item['type']=='table': db.execute(item['sql'])
        for table, rows in saved['rows'].items():
            for row in rows:
                columns = [c for c in row if c!=RID]
                db.execute(f'INSERT INTO {identifier(table)} ({",".join(identifier(c) for c in columns)}) '
                           f'VALUES ({",".join("?" for _ in columns)})', [row[c] for c in columns])
        for item in saved['schema']:
            if item['type']!='table': db.execute(item['sql'])
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise IntegrityError('Backup failed integrity validation')


def prune_database(database: Database, saved: dict, action: dict) -> None:
    """Delete history atomically, restore immutability triggers, verify every saved view."""
    before = {number:load_foundation(database,*pair) for number,pair in action['pairs'].items()}
    with database.transaction():
        if snapshot(database)!=saved:
            raise IntegrityError('Data changed during backup; no cleanup applied')
        database.execute('PRAGMA defer_foreign_keys=ON')
        if database.query('PRAGMA defer_foreign_keys') != [{'defer_foreign_keys':1}]:
            raise IntegrityError('Deferred foreign-key enforcement unavailable')
        triggers = [row for row in saved['schema'] if row['type']=='trigger']
        for trigger in triggers: database.execute('DROP TRIGGER '+identifier(trigger['name']))
        for table, ids in action['removed'].items():
            for start in range(0,len(ids),200):
                chunk = ids[start:start+200]
                database.execute(f'DELETE FROM {identifier(table)} WHERE rowid IN ({",".join("?" for _ in chunk)})',chunk)
        for trigger in triggers: database.execute(trigger['sql'])
        if database.query('PRAGMA foreign_key_check'):
            raise IntegrityError('Cleanup violated a dependency; transaction rolled back')
        for number,pair in action['pairs'].items():
            if load_foundation(database,*pair)!=before[number]:
                raise IntegrityError('Latest saved result changed; transaction rolled back')


def cleanup(database: Database, storage, directory: Path, *, apply: bool) -> dict:
    """Backup before deletion; remove only former indexed objects after SQL commits."""
    saved = snapshot(database)
    action = plan(database,saved)
    report = {'pairs':action['pairs'], 'removed_rows':{t:len(ids) for t,ids in action['removed'].items() if ids},
              'old_objects':len(action['objects']), 'applied':False, 'r2_deleted':0}
    if not apply: return report
    directory.mkdir(parents=True,exist_ok=False)
    backup_database(saved,directory/'before_cleanup.sqlite3')
    (directory/'cleanup_plan.json').write_text(json.dumps(action,indent=2))
    # Verify retained raw bytes too: do not clean a baseline with missing evidence.
    removed_ids=set(action['removed'].get('raw_evidence',[]))
    for row in saved['rows'].get('raw_evidence',[]):
        if row[RID] not in removed_ids:
            verify_checksum(storage.read(row['object_path']), row['checksum'])
    for key,digest in action['objects'].items():
        validate_object_path(key)
        content = storage.read(key)
        verify_checksum(content,digest)
        target = directory/'objects'/key
        target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(content)
    prune_database(database,saved,action)
    report['applied']=True
    pending=[]
    for key in action['objects']:
        try:
            if (database.query('SELECT 1 present FROM raw_evidence WHERE object_path=?',(key,))
                    or database.query('SELECT 1 present FROM company_search_evidence WHERE object_path=?',(key,))):
                raise IntegrityError('A new record now references a pending object')
            if hasattr(storage,'_client'):
                response=storage._client.delete_object(Bucket=storage._bucket,Key=key)
                if response.get('ResponseMetadata',{}).get('HTTPStatusCode') not in (200,204):
                    raise IntegrityError('R2 deletion was not acknowledged')
            else:
                (storage.root/key).unlink()
            report['r2_deleted']+=1
        except Exception:
            pending.append(key)  # SQL already committed; originals are backed up locally.
    report['pending_objects']=pending
    (directory/'cleanup_report.json').write_text(json.dumps(report,indent=2))
    return report
