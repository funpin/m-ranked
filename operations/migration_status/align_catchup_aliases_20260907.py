"""Align unpublished target aliases to original SQLite IDs before final import.

Never changes a UUID, observation, provider identity, or previously imported
mapping. New target-only aliases that occupy SQLite IDs move above both ranges.
"""
import json
from pathlib import Path
import sqlite3
import subprocess
import psycopg
from dotenv import dotenv_values

for platform in ('telegram', 'vk', 'max', 'rutube'):
    state = subprocess.check_output(['systemctl', 'show', f'm-ranked-target-collector@{platform}.service',
                                     '--value', '-p', 'ActiveState'], text=True).strip()
    assert state in ('inactive', 'failed'), (platform, state)
config = dotenv_values('/etc/m-ranked/infra/production.env')
with psycopg.connect(host='127.0.0.1', dbname='mranked', user='mranked_bootstrap',
                     password=config['POSTGRES_SUPERUSER_PASSWORD']) as pg, sqlite3.connect(
        'file:/var/lib/m-ranked/catchup-20260907/final.sqlite?mode=ro&immutable=1', uri=True) as source:
    pg.execute("SET LOCAL lock_timeout='5s'")
    pg.execute('LOCK TABLE catalog.legacy_entity_alias IN ACCESS EXCLUSIVE MODE')
    aliases = {(t, int(i)): str(u) for t, i, u in pg.execute(
        'SELECT entity_type,legacy_id,target_uuid FROM catalog.legacy_entity_alias')}
    rows = list(pg.execute("SELECT publication_id,platform_account_id,external_id FROM ingest.publication_identity WHERE role='primary'"))
    identities = {(str(a), e): str(p) for p, a, e in rows}
    assert len(identities) == len(rows), 'Ambiguous provider identity'
    imported = {(t, int(i)): str(u) for t, i, u in pg.execute(
        "SELECT source_table,source_pk,target_uuid FROM migration.legacy_identity_map "
        "WHERE source_table IN ('posts','platform_posts') AND target_type='publication'")}
    changes = []
    for table, query, account_table in (
        ('posts', 'SELECT id,channel_id,telegram_message_id,telegram_grouped_id FROM posts', 'channels'),
        ('platform_posts', 'SELECT id,platform_account_id,external_id,NULL FROM platform_posts', 'platform_accounts'),
    ):
        desired = {}
        source_ids = set()
        for legacy_id, account_id, external, grouped in source.execute(query):
            source_ids.add(legacy_id)
            account_id = aliases[(account_table, account_id)]
            external = (('g:' + str(grouped)) if grouped is not None else ('m:' + str(external))) if table == 'posts' else str(external)
            native = identities.get((account_id, external))
            if (table, legacy_id) in imported:
                assert native == imported[(table, legacy_id)] == aliases[(table, legacy_id)]
            if native is not None:
                assert native not in desired, 'Two source rows resolve to one publication'
                desired[native] = legacy_id
        existing = {u: i for (t, i), u in aliases.items() if t == table}
        assert desired.keys() <= existing.keys(), 'Native publication has no existing alias'
        next_id = max([*source_ids, *existing.values()]) + 1
        assignments = {}
        for target_uuid, old_id in existing.items():
            new_id = desired.get(target_uuid, old_id)
            if target_uuid not in desired and old_id in source_ids:
                new_id = next_id
                next_id += 1
            assignments[target_uuid] = new_id
        assert len(set(assignments.values())) == len(assignments)
        for target_uuid, new_id in assignments.items():
            old_id = existing[target_uuid]
            if old_id == new_id:
                continue
            assert (table, old_id) not in imported, 'Refusing to move an imported source identity'
            assert target_uuid not in imported.values(), 'Refusing to change an imported publication alias'
            original = pg.execute('SELECT legacy_route,source_hash FROM catalog.legacy_entity_alias WHERE entity_type=%s AND target_uuid=%s',
                                  (table, target_uuid)).fetchone()
            assert original[1] is None, 'An alias already has imported source provenance'
            changes.append(dict(table=table, targetUuid=target_uuid, oldId=old_id, newId=new_id,
                                oldRoute=original[0]))
        temporary = max([*assignments.values(), *existing.values()]) + 1
        for item in (c for c in changes if c['table'] == table):
            pg.execute('UPDATE catalog.legacy_entity_alias SET legacy_id=%s WHERE entity_type=%s AND target_uuid=%s',
                       (temporary, table, item['targetUuid']))
            temporary += 1
        route = '/posts/' if table == 'posts' else '/platform-posts/'
        for item in (c for c in changes if c['table'] == table):
            pg.execute('UPDATE catalog.legacy_entity_alias SET legacy_id=%s,legacy_route=%s WHERE entity_type=%s AND target_uuid=%s',
                       (item['newId'], route + str(item['newId']), table, item['targetUuid']))
    report = {'changes': changes, 'importedMappingsUnchanged': True,
              'publicationUuidsAndObservationsUnchanged': True}
    receipt = Path('/var/lib/m-ranked-migration-status/catchup-alias-alignment-20260907.json')
    assert not receipt.exists(), 'Alignment already has a receipt; inspect before repeating'
    pg.commit()
    receipt.write_text(json.dumps(report, indent=2) + '\n')
    receipt.chmod(0o600)
    print('Aligned', len(changes), 'unpublished native aliases; imported identities and observations unchanged.')
