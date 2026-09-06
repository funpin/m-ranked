"""Read-only canonical, projection and identity verification of an accepted import.

Credentials are supplied only through MRANKED_FROZEN_VERIFY_DSN. PostgreSQL
enforces READ ONLY and all three oracles share one REPEATABLE READ snapshot.
The current source, dataset revision and published projections are never rebuilt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import time

from migration.bridge.identity_history_reconciliation import verify_identity_history
from migration.bridge.model import BridgeOptions
from migration.bridge.projection_reconciliation import verify_projections
from migration.bridge.reconciliation import independent_checks
from migration.bridge.report import write_reports
from migration.bridge.service import BridgeService
from migration.bridge.source import LegacySource, sha256_file
from migration.bridge.target import PostgresTarget
from migration.release_manifest import flyway_manifest, release_identity


def run(args):
    args.output.mkdir(parents=True,exist_ok=False)
    args.output.chmod(0o700)
    source=LegacySource(args.source)
    inventory=source.inventory()
    report={"report_version":1,"report_type":"read-only-frozen-verification",
        "generated_at":datetime.now(timezone.utc).isoformat(),"production_acceptance":False,
        "source":inventory.as_dict(),"release_identity":release_identity(),
        "flyway_manifest":flyway_manifest(),"checks":[],"mismatches":[]}
    started=time.monotonic()
    def check(name, passed, **details):
        item={"check":name,"status":"pass" if passed else "fail","critical":True,**details}
        report["checks"].append(item)
        if not passed: report["mismatches"].append(item)
    try:
        with PostgresTarget(os.environ['MRANKED_FROZEN_VERIFY_DSN']) as target:
            service=BridgeService(BridgeOptions(source=args.source,source_namespace=args.source_namespace,
                preserved_source_paths=tuple(args.preserved_source),historical_source_paths=tuple(args.historical_source)),
                source,target,snapshot_kind=args.snapshot_kind)
            with target.connection.transaction():
                target.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                report['transaction']={'isolation':target.fetchone('SHOW transaction_isolation')[0],
                    'readOnly':target.fetchone('SHOW transaction_read_only')[0]=='on'}
                actual=target.fetchall('SELECT version,script,checksum,success FROM flyway.flyway_schema_history WHERE version IS NOT NULL ORDER BY installed_rank')
                manifest=[dict(zip(('version','script','checksum','success'),row,strict=True)) for row in actual]
                check('exact_flyway_manifest',manifest==[{k:v for k,v in row.items() if k!='sha256'} for row in report['flyway_manifest']])
                revision=target.fetchone('SELECT max(id) FROM analytics.dataset_revision')[0]
                report['dataset_revision']=revision
                check('expected_revision',revision==args.expected_revision,expected=args.expected_revision,actual=revision)
                for name,comparison in independent_checks(service):
                    check('canonical_target_digest',comparison['expected']==comparison['actual'],scope=name,**comparison)
                projection=verify_projections(args.source,target.connection,source_name=args.source_namespace,
                    expected_sha256=inventory.source_sha256,first_age_limit_seconds=args.first_age_limit_seconds,
                    preserved_source_paths=tuple(args.preserved_source))
                report['projection_verification']=projection
                check('derived_projection_parity',projection['status']=='pass',details=projection)
                history=verify_identity_history(service,historical_source_paths=tuple(args.historical_source))
                report['identity_history_verification']=history
                check('identity_history_parity',history['status']=='pass',details=history)
        check('source_artifact_unchanged',sha256_file(source.path)==inventory.source_sha256)
    except Exception as error:
        check('verifier_completed',False,errorCode=type(error).__name__)
        raise
    finally:
        report['duration_seconds']=round(time.monotonic()-started,6)
        report['gate']={'status':'fail' if report['mismatches'] else 'pass','critical_mismatches':len(report['mismatches'])}
        write_reports(args.output,'verification',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--source-namespace',required=True)
    parser.add_argument('--snapshot-kind',choices=('s0','catch_up','s_final','fixture'),default='s_final')
    parser.add_argument('--expected-revision',type=int,required=True)
    parser.add_argument('--first-age-limit-seconds',type=int,default=360)
    parser.add_argument('--preserved-source',type=Path,action='append',default=[])
    parser.add_argument('--historical-source',type=Path,action='append',default=[])
    parser.add_argument('--output',type=Path,required=True)
    report=run(parser.parse_args())
    print(f"Frozen verification: {report['gate']['status']}; revision={report.get('dataset_revision')}; critical={report['gate']['critical_mismatches']}",flush=True)
    raise SystemExit(0 if report['gate']['status']=='pass' else 1)


if __name__=='__main__': main()
