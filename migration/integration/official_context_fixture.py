"""Original legacy institutions/channels with deliberately different official ranks."""
from __future__ import annotations
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
from app.database import Database
from migration.bridge.fixture import build_golden_fixture, FIXTURE_ANCHOR
from migration.bridge.model import BridgeOptions
from migration.bridge.service import BridgeService
from migration.bridge.source import LegacySource
from migration.bridge.target import PostgresTarget


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--oracle',type=Path,required=True)
    parser.add_argument('--with-state',action='store_true')
    args=parser.parse_args()
    build_golden_fixture(args.database,revision=2)
    db=Database(args.database)
    second=db.add_channel('second_official',1)
    unrated=db.add_channel('unrated_official',1)
    db.update_channel_m_rating(second,3,90.0,'channel-period',FIXTURE_ANCHOR+timedelta(minutes=10))
    db.update_institution_m_rating(1,{'tg':(11,77.0)},'institution-period',FIXTURE_ANCHOR)
    if args.with_state:
        db.set_state('m_rating_last_period','2026-Q2')
        db.set_state('m_rating_last_updated',(FIXTURE_ANCHOR+timedelta(minutes=11)).isoformat())
        db.set_state('m_rating_last_error','Synthetic fixture source failure')
    with db.connect() as source:
        source.execute('UPDATE channels SET added_at=?', (FIXTURE_ANCHOR.isoformat(),))
        source.execute('UPDATE platform_accounts SET added_at=?', (FIXTURE_ANCHOR.isoformat(),))
        source.execute("UPDATE platform_accounts SET access_mode='public',last_error='Synthetic fixture source failure' WHERE platform='rutube'")
    anchor=(FIXTURE_ANCHOR+timedelta(minutes=20)).timestamp()
    os.utime(args.database,(anchor,anchor))
    with db.connect() as source:
        institution=dict(source.execute('SELECT * FROM institutions WHERE id=1').fetchone())
        channels=[dict(row) for row in source.execute('SELECT id,m_rating_tg_rank,m_rating_tg_score FROM channels WHERE institution_id=1 ORDER BY id')]
        accounts=[dict(row) for row in source.execute("SELECT id,access_mode,last_error FROM platform_accounts WHERE platform<>'telegram' ORDER BY id")]
    args.oracle.write_text(json.dumps({'institutionId':1,'rank':institution['m_rating_tg_rank'],'score':institution['m_rating_tg_score'],
        'channels':channels,'periodState':db.get_state('m_rating_last_period'),'updatedState':db.get_state('m_rating_last_updated'),
        'errorPresent':bool(db.get_state('m_rating_last_error')),
        'accounts':[{'id':row['id'],'accessMode':row['access_mode'],'errorPresent':bool(row['last_error'])} for row in accounts]},ensure_ascii=False))
    with PostgresTarget(os.environ['BRIDGE_DATABASE_URL']) as target:
        _,report=BridgeService(BridgeOptions(source=args.database,source_namespace='official-context',batch_size=100),LegacySource(args.database),target,snapshot_kind='fixture').run()
        if report['gate']['status']!='pass': raise RuntimeError('Official fixture reconciliation failed')
    print('Original legacy official context imported; no source state inferred from observation dates.')


if __name__=='__main__':main()
