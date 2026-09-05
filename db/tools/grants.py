import re, pathlib
S='/private/tmp/claude-501/-Users-akko-Documents-GitHub-m-ranked/64e9323d-5927-4cea-a794-ff75cdf7819d/scratchpad'
OUT=pathlib.Path('/Users/akko/Documents/GitHub/m-ranked/db/migrations/0017_grants.sql')
src=pathlib.Path(f'{S}/schema/live-dump-grants.sql').read_text().splitlines()

PART=re.compile(r'_(?:19|20)\d{2}_\d{2}(?:\s|;)')
DROPPED=('publication_hourly','comparison_publication_hourly','comparison_metric_point',
         'projection_state','rebuild_core_projections','rebuild_serving',
         'intern_metric_evidence','compact_metric_evidence','latest_fully_published',
         'compact_new_metric_evidence','refresh_publication_content','flyway')
# the stub overload was removed; _v21 stays — match the exact signature
STUB=re.compile(r'\bdrop_publication_metric_partition\(')
DROPPED_ROLES=('migration_bridge',)

kept=[]; skipped={'partition':0,'object':0,'role':0,'stub':0}
for ln in src:
    if not ln.startswith(('GRANT','REVOKE','ALTER DEFAULT PRIVILEGES')): continue
    if PART.search(ln): skipped['partition']+=1; continue
    if any(d in ln for d in DROPPED): skipped['object']+=1; continue
    if STUB.search(ln): skipped['stub']+=1; continue
    if any(f'TO {r};' in ln for r in DROPPED_ROLES): skipped['role']+=1; continue
    kept.append(ln)

by_role={}
for ln in kept:
    m=re.search(r'\bTO ([a-z_]+);', ln)
    by_role.setdefault(m.group(1) if m else 'служебные (REVOKE)', []).append(ln)

L=["-- 0017 — права ролей","-- Порождается из каталога эталонной базы; см. db/README.md.",
   "-- Права на партиции наследуются от родительской таблицы и отдельно не выдаются.",""]
for role in sorted(by_role):
    L.append(f"-- {role} ({len(by_role[role])})"); L.extend(by_role[role]); L.append("")
OUT.write_text("\n".join(L))
print("отброшено:", skipped, "| записано:", len(kept))
