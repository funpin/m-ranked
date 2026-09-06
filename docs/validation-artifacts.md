# Validation artifact storage

Generated validation output belongs in local run directories or CI artifacts.
The repository retains historical summary reports, acceptance decisions,
reproduction scripts and test fixtures. New runs under `frontend/evidence/`,
`migration/reports/` and `operations/**/evidence/` are ignored by Git.

The September 2026 cleanup removed raw DOM, PNG, accessibility-tree and
per-page axe/computed-style captures, progress snapshots, process logs,
JUnit exports, generated changed-file inventories and rehearsal Parquet
archives from the current tree. The existing local copies were kept.
This does not rewrite Git history or reduce the size of historical clones.

## Historical reports

The retained reports describe past runs. Paths and checksums inside them
refer to the original artifacts, which are no longer all present in a fresh
checkout. A summary alone is not a complete evidence bundle or a new release
approval. The historical bundle is available at commit
`1e52f415fbdedc15f10e3d992e5126b8b7c92925`.

For example, extract the final visual run into an existing directory outside
the checkout (the command needs the historical commit in the local clone):

```sh
git archive 1e52f415fbdedc15f10e3d992e5126b8b7c92925 \
  frontend/evidence/visual-full-v29-r2-final | tar -x -C /path/to/artifact-storage
```

## New runs

Keep raw output in the ignored run directories, then upload the required
evidence bundle as a CI artifact or to the team's chosen artifact storage.
Do not use `git add -f` to commit complete generated run directories.
The migration workflow already uploads integration and browser evidence
through `actions/upload-artifact`.

When a summary must be versioned, prefer a concise document outside the
ignored output directories with the source commit, run outcome, artifact
location and checksums. Keep fixtures and application assets in their
existing source directories; the output ignore rules do not apply to them.
