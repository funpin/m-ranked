# Identity receipt Unix permissions rehearsal

Run from the repository with Docker and Java 21 available:

```bash
rtk proxy env JAVA_HOME=/path/to/jdk-21 .venv/bin/python \
  -m operations.identity_receipts.rehearse \
  --output /private/tmp/mranked-receipt-permissions-NEW
```

The output directory must be new. The verifier compiles the actual Java receipt
producer and its small test entrypoint, mounts repository/classes read-only in
one disposable Linux container, and installs Python only there. It disconnects
the container network before exercising filesystem permissions and removes only
its own container afterward. It changes no host users, groups or receipt files.
The image identity, source SHA-256s, commands, timings and results are retained.

Five real process UIDs represent Java admin, Python collector, reverse reader,
backup reader and an unrelated user. Writers have no supplementary reader GID.
The actual `IdentityCommandEvidence` and `IdentityEvidenceStore` implementations
prove private `0700`/`0400` compatibility, shared `2750`/`0440` creation and exact
retry, metadata-only conversion with unchanged content hashes/owner UIDs, and
simultaneous private/shared subtrees. Both readers can read both producers;
writers cannot access each other's objects; readers cannot modify, delete or
publish objects; outsiders cannot read. Unsafe modes, owner/GID mismatches and
symlink ancestors fail closed.

The [V29 local proof](evidence/local-v29-readers-r1/report.json) passed all 13
permission checks in 18.689 seconds, including provisioning and cleanup. See
[deployment and recovery instructions](../runbooks/IDENTITY_RECEIPTS.md) for the
required service ownership and supplementary groups. This evidence proves the
repository's Linux permission contract. It does not attest production group
membership, remote receipt replication, restore inventories or operator approval;
production Writer Gate W remains closed.
