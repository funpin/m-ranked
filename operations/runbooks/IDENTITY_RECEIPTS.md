# Durable identity receipts

Administrative identity commands and collector-discovered native identities are
persisted before their database transaction. PostgreSQL receipts bind their
SHA-256; they do not replace the original immutable JSON object.

Root: `/var/lib/m-ranked/identity-receipts`.

| Leaf | Writer |
|---|---|
| `admin/` | `m-ranked-api` |
| `collector/<platform>/` | corresponding collector user |

Each leaf is owned by its writer, setgid mode `2750`, group
`m-ranked-identity-readers`. Receipt objects are mode `0440`. Writers are not
members of the reader group and cannot read each other's leaves. Backup and
restore users receive supplementary read-only group access.

Never recursively widen permissions or synthesize a missing receipt from
database rows. Back up the receipt tree outside PostgreSQL, retain it as long as
the referenced identity history, and verify filenames against content hashes
after restore. Private single-owner `0700/0400` stores remain supported for
local use.
