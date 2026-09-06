"""Regenerate exact operational schema pins; never edits a Flyway migration.

Run only when the additive schema is ready for a new release, then review diff
and run operational tamper tests. This produces literal pins, never a runtime
accept-any-new-version rule. V1-V8 remain independently pinned in their tests.
"""
from __future__ import annotations
from pathlib import Path
import json
import re
from migration.release_manifest import ROOT, flyway_manifest


def sub(text, pattern, replacement, *, count=0):
    changed, matches=re.subn(pattern,lambda _m:replacement,text,count=count,flags=re.M|re.S)
    if not matches:
        raise ValueError(f"schema pin block not found: {pattern[:90]}")
    return changed


def main():
    manifest=flyway_manifest()
    count=len(manifest)
    version=str(count)
    rows=tuple((m['version'],m['script'],m['sha256'],m['checksum']) for m in manifest)
    versions=[m['version'] for m in manifest]
    names=sorted(m['script'] for m in manifest)
    pins='EXPECTED_MIGRATIONS = (\n'+''.join(f'    {r!r},\n' for r in rows)+')\n'
    path=ROOT/'operations/collector_parity_evidence.py'
    text=path.read_text()
    text=sub(text,r'^EXPECTED_MIGRATIONS = \(\n.*?^\)\n',pins,count=1)
    text=re.sub(r'flyway.get\("schemaVersion"\) != "\d+"',f'flyway.get("schemaVersion") != "{version}"',text)
    text=re.sub(r'"deploy flyway.migrationCount", \d+\) != \d+',f'"deploy flyway.migrationCount", {count}) != {count}',text)
    text=re.sub(r'schema_version != \d+ or migration_count != \d+',f'schema_version != {count} or migration_count != {count}',text)
    text=re.sub(r'"(migrationCount|schemaVersion)": \d+',lambda m:f'"{m[1]}": {count}',text)
    text=re.sub(r'V1-V\d+',f'V1-V{version}',text)
    path.write_text(text)

    path=ROOT/'operations/scripts/deploy-shadow.sh'
    text=path.read_text()
    text=sub(text,r'(?m)^  backend/src/main/resources/db/migration/V1__.*?^  frontend/server.js',
             ''.join(f'  backend/src/main/resources/db/migration/{m["script"]}\n' for m in manifest)+'  frontend/server.js',count=1)
    listing="expected_migration_files=\"$(printf '%s\\n' \\\n"+' \\\n'.join('  '+name for name in names)+')"'
    text=sub(text,r'^expected_migration_files="\$\(printf.*?\)"',listing,count=1)
    capture='capture_frozen_release_provenance() {\n  local tree="$1"\n  captured_manifest_sha256="$(sha256sum "$tree/SHA256SUMS" | cut -d\' \' -f1)"\n'
    capture+=''.join(f'  captured_v{m["version"]}_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/{m["script"]}" | cut -d\' \' -f1)"\n' for m in manifest)
    capture+='  if [[ '+' \\\n        || '.join(f'"$captured_v{m["version"]}_sha256" != {m["sha256"]}' for m in manifest)+' ]]; then\n'
    capture+=f'    echo "frozen Flyway V1-V{version} checksum mismatch" >&2\n    return 65\n  fi\n}}\n'
    text=sub(text,r'^capture_frozen_release_provenance\(\) \{\n.*?^\}\n',capture,count=1)
    text=re.sub(r'(?m)^( *)v1_hash="\$captured_v1_sha256"\n(?: *v\d+_hash="\$captured_v\d+_sha256"\n)+',
                lambda m:''.join(f'{m[1]}v{x["version"]}_hash="$captured_v{x["version"]}_sha256"\n' for x in manifest),text)
    text=re.sub(r'\.schemaVersion == "\d+"',f'.schemaVersion == "{version}"',text)
    text=re.sub(r'\(\.migrations \| length\) == \d+',f'(.migrations | length) == {count}',text)
    text=sub(text,r'(    and \(\[\.migrations\[\] \| \.version\] \| sort\)\n        == )\[[^\n]*\]',
             '    and ([.migrations[] | .version] | sort)\n        == '+json.dumps(sorted(versions)),count=1)
    text=sub(text,r'^  --arg v1Sha256.*?(?=^  --arg (?!v\d+Sha256)|^  \'\{)',
             ''.join(f'  --arg v{m["version"]}Sha256 "$v{m["version"]}_hash" \\\n' for m in manifest),count=1)
    text=re.sub(r'schemaVersion:"\d+",migrationCount:\d+',f'schemaVersion:"{version}",migrationCount:{count}',text)
    text=sub(text,r'v1Sha256:\$v1Sha256,.*?validated:true',','.join(f'v{m["version"]}Sha256:$v{m["version"]}Sha256' for m in manifest)+',validated:true',count=1)
    text=re.sub(r'V1-V\d+',f'V1-V{version}',text)
    path.write_text(text)

    path=ROOT/'operations/scripts/cutover-preflight.sh'
    text=path.read_text()
    text=re.sub(r'(\.(?:flyway\.)?(?:schemaVersion|migrationCount)|\.database\.flyway(?:SchemaVersion|MigrationCount)) == ("?)\d+\2',
                lambda m:f'{m[1]} == {m[2]}{count}{m[2]}',text)
    text=sub(text,r'and \(\.flyway.fileSha256 \| type == "object" and keys == \[.*?\]\)',
             'and (.flyway.fileSha256 | type == "object" and keys == '+json.dumps(names)+')',count=1)
    text=sub(text,r'and \.flyway.fileSha256 == \{[^}]*\}',
             'and .flyway.fileSha256 == '+json.dumps({m['script']:m['sha256'] for m in manifest},sort_keys=True),count=1)
    dbrows='[\n'+',\n'.join(f'        {{version:"{m["version"]}",script:"{m["script"]}",checksum:{m["checksum"]},success:true}}' for m in manifest)+'\n      ]'
    text=sub(text,r'and \.flyway.databaseMigrations == \[.*?\n      \]', 'and .flyway.databaseMigrations == '+dbrows,count=1)
    text=sub(text,r'(?:      and \.flyway.v\d+Sha256 == "[0-9a-f]+"\n)+',
             ''.join(f'      and .flyway.v{m["version"]}Sha256 == "{m["sha256"]}"\n' for m in manifest),count=1)
    text=sub(text,r'and \.database.flywayMigrations == \[[^\]]*\]',
             'and .database.flywayMigrations == [\n'+',\n'.join(f'          {{version:"{m["version"]}",script:"{m["script"]}",checksum:{m["checksum"]}}}' for m in manifest)+'\n      ]',count=1)
    text=re.sub(r'V1-V\d+',f'V1-V{version}',text)
    if text.count('\n') < path.read_text().count('\n') * .8:
        raise ValueError('schema regeneration unexpectedly removed control flow')
    path.write_text(text)

    path=ROOT/'operations/scripts/restore-verify.sh'
    text=path.read_text()
    text=re.sub(r'migration_count <> \d+ OR latest_migration <> \d+',f'migration_count <> {count} OR latest_migration <> {count}',text)
    text=sub(text,r"ARRAY\['1',.*?\]::text\[\]",'ARRAY['+', '.join(repr(v) for v in versions)+']::text[]',count=1)
    text=sub(text,r'FROM \(VALUES\n.*?\n             \) AS expected\(version, script, checksum\)',
             'FROM (VALUES\n'+',\n'.join(f"                 ('{m['version']}', '{m['script']}', {m['checksum']})" for m in manifest)+'\n             ) AS expected(version, script, checksum)',count=1)
    text=re.sub(r'V1-V\d+',f'V1-V{version}',text)
    path.write_text(text)
    print(f'Pinned exact V1-V{version} operational manifest; run tamper tests before release.')


if __name__=='__main__': main()
