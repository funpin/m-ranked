# Durable original account identity inputs

Account identity reconciliation needs original accepted inputs for target-side
changes as well as every imported SQLite artifact. The local receipt directory
is an original-input store. PostgreSQL command receipts and revision metadata
bind accepted object hashes, order and times; they never supply expected identity
values to the independent oracle.

Set `MRANKED_IDENTITY_RECEIPT_DIR=/var/lib/m-ranked/identity-receipts` consistently
for the API, all four collectors, reverse sync and migration/reconciliation
operator. Its
layout separates write ownership:

| Path under root | Writer | Contents |
|---|---|---|
| `admin/` | `m-ranked-api` | Allowlisted original command envelope, named by request digest |
| `collector/telegram/` | `m-ranked-collector-telegram` | Minimal original identity envelope named by SHA-256 |
| `collector/vk/` | `m-ranked-collector-vk` | Same |
| `collector/max/` | `m-ranked-collector-max` | Same |
| `collector/rutube/` | `m-ranked-collector-rutube` | Same |

Provision the two parent directories as root-owned mode `0755`; each writer
subdirectory is setgid mode `2750`, owned by its listed service user and group
`m-ranked-identity-readers`. Immutable receipt files are `0440` and must have
exactly the directory's owner UID and group GID. API and collector users are
**not members** of the reader group. They can write their own subtree through
owner permissions, but cannot read or write another writer's receipts. Do not
make any receipt directory group/world writable.

The reverse unit (`telegram-monitor`), backup unit (`m-ranked-backup`) and
isolated restore/PITR units (`m-ranked-restore`) receive the reader group through
`SupplementaryGroups=m-ranked-identity-readers`. They can read both producer
types but cannot publish, modify or remove files. Their existing primary groups
and database grants do not change. Interactive reconciliation needs the same
read-only group or the existing privileged cutover context. The systemd units
still allow writes only to each writer's corresponding subtree.

Private single-UID fixtures remain supported: an exact `0700` directory with
`0400` files owned by that directory's owner. Merely making a directory `0750`
or a file group-readable does not enable shared mode. Both implementations reject
unsafe modes and symlink ancestors; shared files also require the inherited GID.

## Existing private receipts and restored copies

Fence all API/admin and collector writers before converting an existing private
tree. Inventory only regular `<64 lowercase hex>.json` objects in the five
known writer leaves: verify each name equals its content SHA-256, its original
owner matches that leaf's designated service user, mode is `0400`, and no path
has a symlink ancestor. Record SHA-256, UID, GID and mode in the change evidence;
keep the original inventory and protected backup. Unexpected entries or modes
require investigation, not a broad recursive `chmod` or `chown`.

For each verified leaf, retain its writer UID, set its group to
`m-ranked-identity-readers` and mode to `2750`. For each inventoried receipt,
retain its UID and bytes, set only its group to that reader group and mode to
`0440`. Fsync the changed files and directories. Compare the complete inventory
afterward: every filename, content SHA-256 and writer UID must remain identical.
An incomplete conversion fails closed; producers never repair old permissions
implicitly. Verify an exact producer retry plus reads as the actual reverse and
backup users before reopening writers.

Apply the same checked ownership/mode restoration on an isolated restore host.
Numeric UIDs/GIDs from another host are not automatically authoritative: bind
the inventory to the provisioned service identities and retain evidence of any
metadata-only remapping. The restore reader must not own writer directories.
Do not grant it write access to the preserved receipt inventory.

The producer durably publishes the original input before database commit. A
failed filesystem write/fsync prevents a successful command. Aborted database
transactions can leave unreferenced objects: the oracle enumerates committed
bindings and ignores those orphans. Do not convert an arbitrary JSON file or
target audit row into an accepted source. Missing/corrupt objects, symlinks,
invalid bounds or incompatible committed bindings close the history gate.

Minimal identity inputs have a different lifetime from provider raw payloads.
Seven-day raw expiry must not remove the only source of a retained identity
interval. Keep every referenced identity receipt for as long as its associated
identity history and recoverable backups; no automatic receipt purge is enabled.

Native-ID removal does not reset the timeline. V29 places each administrative
transition after the latest boundary across both active and closed native-ID
versions. Collectors retain their original provider timestamps and reject stale
or equal-time re-enrollment after a closed interval; they do not move observation
times to make history appear consistent. Failed batches remain subject to the
normal durable retry/failure handling. Earlier identity rows stay immutable.

## Backup and restore boundary

These files are outside PostgreSQL and are not included in `pg_basebackup` or
pgBackRest by themselves. Replicate them to the protected off-primary backup
domain and include them in the recovery inventory with the original SQLite
artifacts. Database commits can reference only already durable objects; a backup
set must contain every receipt referenced by its restored revision. Additional
unreferenced objects do not alter the accepted event stream.

Restore PostgreSQL first into the isolated verifier, restore the corresponding
receipt/source inventory, then run full S_final reconciliation against that
restored database with `MRANKED_IDENTITY_RECEIPT_DIR` pointing at the protected
restored tree and every original `--historical-source` explicitly supplied.
Require exact canonical, projection and identity-history PASS at the recovered
revision. Physical checksum/PITR success alone does not prove these external
source objects are recoverable. Never reopen Writer Gate W with a missing
receipt, and never recover by inventing a receipt from the restored target rows.

Production off-primary retention/encryption and recovery acceptance require the
database/data operators' separate approved rehearsal. Local evidence does not
attest a deployed remote storage provider or authorize production changes.

The [reproducible Linux rehearsal](../identity_receipts/README.md) exercises both
actual producers under separate UIDs and verifies the reverse/backup reader
permissions, metadata-only conversion and fail-closed cases.
