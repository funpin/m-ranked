# Disposable HTTP upstream transition rehearsal

This executable verifier adds a real network deployment layer to
`tests/test_reverse_sync_postgres.py::test_postgres_reverse_sync_round_trip_preserves_target_identity`.
It launches the actual legacy FastAPI application under Uvicorn, the built Spring JAR with
a private read login inheriting `api_read` privileges, the authenticated `api_write_admin`
command path, and a loopback HTTP reverse proxy. It never modifies a
production upstream, a shared runtime, or a shared database role.

Run with Docker, Java 21, Maven, and the existing Python environment:

```sh
rtk proxy .venv/bin/python -m operations.http_transition.rehearse \
  --output /private/tmp/mranked-http-rehearsal-unique
```

`JAVA_HOME`, `MAVEN_USER_HOME`, and optional `MRANKED_MAVEN_REPOSITORY` select local
toolchains. The runner generates credentials and a UUID Compose project, creates one empty
`http_reverse_it` database, applies the current release with real Flyway, builds Spring,
runs the integrated round trip without skips, and removes its own containers and volumes.
Credentials are passed through the environment and private temporary file; retained command
logs redact generated secrets. Choose a fresh output directory: evidence is never overwritten.

The four routing phases use the same real dataset:

1. Legacy owns writes during online S0, interrupted/resumed import, and live catch-up.
2. The green S-final reconciliation and actual target readiness admit target traffic.
   SQLite `BEGIN IMMEDIATE` freezes the old writer before target collector access opens.
   All four target platform collectors commit real normalized observations. Original-input
   receipts prove native NULL → N → N+1 and presentation changes. Four authenticated Java
   commands then change presentation, change native ID, clear it and reassign it; each exact
   command replay must return the same result without another revision.
3. Reverse sync drains, independently verifies, and stops. Target collector and admin CONNECT are
   revoked before checking that their existing sessions drained. A new legacy HTTP server
   opens the exact synchronized SQLite database and becomes the active upstream/writer.
4. A new `s_final` import verifies preserved canonical identity and complete history against
   every original artifact and receipt. Its exact completed-batch repeat writes zero rows
   without advancing the revision. Missing/corrupt collector and admin receipts block the
   same admission path. The green repeat returns traffic to target.

The proxy continuously forwards `/health` and `/read?platform=telegram|vk|max|rutube` to
the real applications. Target reads use `/api/v1/overview`; legacy reads use its actual
HTML overview. Responses must be successful and contain real nonempty application data.
Evidence records every response's upstream, phase, status, byte count, content hash,
revision where available, and monotonic timing. No response fixture or handler counter
stands in for an application request.

Health continuity uses the legacy-compatible health response, including explicit collector
freshness fields. Actual legacy/target JSON parity is verified after S-final. Target **readiness** separately gates
admission: an empty/unready target is rejected even with a green supplied data gate. During
collector lag, public reads continue serving the last published revision; the verifier does
not disguise readiness lag as readiness success. A critical mismatch is also submitted to
the same transition entry point before each target admission; it must preserve routing and
writer ownership. Actual rolled-back SQLite UPDATE, collector INSERT and admin command probes demonstrate
that only the authoritative writer can write, including the brief both-frozen handoff.
The reverse-sync process intentionally writes a separate shadow SQLite during the target phase.

Output includes `http-transition.json`, its SHA-256 sidecar, a short Markdown report,
`reverse-http.json` (full S0/S-final/reverse/identity evidence and exact Flyway checksums),
JUnit XML, build logs, and private temporary application state. Failure logs remain for
inspection and do not produce a successful HTTP report. Do not publish the large build or
temporary SQLite state; retain the small reports and checksums as release evidence.

An existing self-provisioned integration runner may opt in by setting
`MRANKED_HTTP_REHEARSAL_JAR`, `MRANKED_HTTP_REHEARSAL_JAVA`, and
`MRANKED_HTTP_REHEARSAL_API_READ_DSN` and `MRANKED_HTTP_REHEARSAL_API_WRITE_ADMIN_DSN` alongside the reverse test's existing four role DSNs
and `MRANKED_TEST_REVERSE_SYNC_REPORT_PATH`. All DSNs must refer to the same explicit
loopback `*_it` database, initially empty apart from the exact Flyway release.
Its caller owns database provisioning. The disposable bootstrap credential must have
CREATEROLE: the verifier creates one unique read login, grants it membership in `api_read`,
and removes it on cleanup. This avoids the real inheritance trap where `api_write_admin`
can still CONNECT through its `api_read` membership after a direct admin revoke. Existing
roles are not altered; only this database loses the inherited CONNECT route. Database ACLs
are restored, the private read login is removed, and the caller removes its database/cluster.

Validate the untouched `reverse-http.json` with the actual deployment JQ protocol predicate:

```sh
rtk proxy .venv/bin/python -m operations.reverse_sync.rehearsal_contract \
  /private/tmp/mranked-http-rehearsal-unique/reverse-http.json \
  --output /private/tmp/mranked-http-rehearsal-unique/protocol-validation.json
```

The validator records the input and predicate hashes and never promotes local evidence to
production. Preflight retains its independent active-release/operator/approval/freshness
checks. Report contract v4 requires the complete second S-final, original receipts,
failure probes, real HTTP phases and admin/collector writer ownership.

The exact V29 run is retained in
[evidence/local-v29-final-r1/report.json](evidence/local-v29-final-r1/report.json):
835 requests, zero errors, p95 57.174 ms over 41.798381 seconds; seven rejected
gates and four real Java admin commands. First S-final R66 advanced to the new
S-final R111, whose repeat wrote zero rows at unchanged R111. The untouched
actual report also [passed the same JQ protocol predicate](evidence/local-v29-final-r1/protocol-validation.json).
The V28 failed attempts remain historical evidence and are not acceptance
proofs. **Production Writer Gate W remains CLOSED.**

The separate [actual Nginx proof](evidence/local-v29-nginx-r1/report.json) uses
the unchanged rollback route fragments and the shipped worker-generation
barrier in Nginx 1.28.3. It preserved 159 continuous reads with zero failures
(p95 4.382 ms) and rejected 46 mutation/admin requests. A held prior POST
completed before the 0.702-second freeze admission; the old keepalive connection
was closed. The [initial failed probe](https://github.com/funpin/m-ranked/blob/1e52f415fbdedc15f10e3d992e5126b8b7c92925/operations/http_transition/evidence/local-v29-nginx-failed-r1/probe.log)
is retained: it exposed a mutation accepted by an old worker after reload.

Reproduce that bounded routing check independently:

```sh
rtk proxy .venv/bin/python -m operations.http_transition.nginx_rehearse \
  --output /private/tmp/mranked-nginx-freeze-NEW
```

It installs Nginx/Python only in its own disposable container and disconnects
network before testing. `SYS_PTRACE` applies only inside the private container
PID namespace so the privileged verifier can inspect worker executable/start
identities after their UID drop. No host PID namespace or production paths are
exposed. This check verifies actual Nginx routing with a loopback transport
upstream; application semantics are covered by the separate real FastAPI/Spring
round trip above. It does not pretend to run production systemd or the full
protected deployment entrypoint.

This is measured local rehearsal evidence, not production acceptance. Production load
balancer configuration, TLS, separate hosts, traffic capacity, and operator cutover approval
remain separate release gates. Repeat against the frozen final release if migrations or
the application artifact change after a successful rehearsal.
