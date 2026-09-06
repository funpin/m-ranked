# Temporary migration homepage

`index.html` polls the same-origin `/migration-status.json` every ten seconds.
The public JSON contains only aggregate counters and an operator-facing phase
translated into a public message. Failed requests retain the last confirmed
counts. No credentials, source filenames, account identifiers or raw errors are
published. Nginx must send `Cache-Control: no-store` for both endpoints.

`publish.py` rereads a private control JSON each cycle. The initial inventory is
the verified online SQLite backup inventory, with `quick_check: ["ok"]`, zero
`foreign_key_violations`, source `sha256`, and `tables[stream].count`. The total
includes the ten bridge source streams, not just metric snapshots. Files in the
separate CSV archive are backed up and verified separately.

Control fields:

```json
{
  "inventoryPath": "/private/path/to/inventory.json",
  "phase": "preparing",
  "message": "Проверяем резервную копию перед переносом.",
  "sourceNamespace": "m-ranked-production",
  "batchId": null
}
```

Only `preparing` and `blocked` allow a null batch, and both publish zero
transferred rows. For an active import, set the exact `batchId` and privately
provision `MRANKED_PROGRESS_DATABASE_URL`/`PGPASSFILE`; the Python environment
must have psycopg. The publisher uses a read-only transaction and checks the
batch's source namespace, source SHA-256 and `dry_run=false` before reading its
committed checkpoints. It never sums checkpoints from multiple batches. When
moving to a catch-up or final snapshot, change the inventory and batch binding
together. A database failure keeps the previous counts and timestamp and marks
them unavailable. Completion of import is not proof of final acceptance; the
verified cutover workflow must remove the temporary homepage after acceptance.

The timer estimates loading the bound snapshot from committed checkpoints over
the last ten minutes, with a two-minute exponential smoothing time constant.
At startup and after a pause it waits for a minute of fresh samples. Paused
phases and failed status reads reset the window, excluding restart downtime.
The estimate may increase during sustained slowdowns. After sixty seconds
without a new checkpoint it is unavailable, rather than counting down toward
a misleading completion time. Catch-up and validation are separate phases.

Production installation made on 2026-09-06:

- Public assets: `/var/www/m-ranked-migration/`.
- Private control and publisher: `/var/lib/m-ranked-migration-status/`.
- Unit: `m-ranked-migration-status.service`.
- Preserved preceding Nginx config:
  `/var/lib/m-ranked-migration-status/nginx-before.conf`.
- Only exact `/` and `/migration-status.json` locations were added to the HTTPS
  server for `m.funpin.org`. Other locations retain the legacy upstream.

The public homepage uses `root /var/www/m-ranked-migration;` with
`try_files /index.html =503;` in `location = /`. Do not alias `/` directly to an
HTML filename: the Nginx index handler appends another `index.html` and returns
HTTP 500. Validate both the HTML and JSON after reload, allowing the previous
worker generation to drain. Serialize route changes using the existing
`/run/lock/m-ranked-transition.lock`. Do not restore the preserved config over
later unrelated routing changes without reviewing their diff.
