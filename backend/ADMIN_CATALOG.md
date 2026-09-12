# Administrative catalogue and legacy forms

Production ownership remains with legacy. Writer Gate W is CLOSED. The API and
Next adapters described here are candidates until their complete release gates
and the separately authorized production transition pass.

## Configuration and permissions

The public data source uses `api_read`. Enable the separate administrative
connection with `MRANKED_ADMIN_DATABASE_ENABLED=true` and the URL, username and
password properties under `mranked.admin.database`. Its database role is
`api_write_admin`; it cannot read raw observations or migration evidence.
Configure named users with bcrypt password hashes under
`mranked.admin.auth.users`. Credentials are server configuration and never
public cache input, browser bundles or audit payload fields.

`VIEWER` reads the catalogue, session and status. `EDITOR` also creates and
updates institutions/accounts, toggles monitoring, sets native IDs and imports
official ratings. `ADMIN` additionally deletes monitored entities. Both route
authorization and application method authorization enforce these roles.
Destructive legacy form commands receive the same role check.

Direct API writes require authenticated Basic access, a CSRF cookie/header pair
from the session endpoint, and a correlation UUID. The Next `/manage/**` facade
preserves the legacy form validation order and last-value semantics, forwards
the authenticated identity, and bounds body and response bytes. It validates
origin and CSRF before executing the command. Administrative responses use
`Cache-Control: no-store`.

## Atomic commands and identities

V16 implements catalogue commands through a restricted SQL function. Catalogue
changes, identity history, projection publication, dataset revision, outbox,
append-only audit and immutable receipt commit in the same transaction. A
global advisory transaction lock serializes projection writers. Matrix updates
run as one transaction; a late conflict rolls back the whole matrix.

A receipt is identified by actor and correlation UUID and binds the request
digest. Exact replay returns its original result. Reusing the correlation UUID
for another request returns 409. The actor comes from authentication; an
untrusted actor header cannot alter audit attribution.

Modern updates require the observed `rowVersion`. Omitting the version requests
a new enrollment and conflicts with an existing active account; a stale or
deleted version never creates a replacement implicitly (V20). Legacy forms
retain their original upsert behavior. HTTP(S) catalogue URLs are display
values and are not fetched by these commands.

Deletion hides an enrollment and preserves its immutable observation/identity
history. Re-enrollment gets a new internal identity and legacy alias. Setting a
native ID appends external-identity history and leaves the canonical key
unchanged. Channel deletion also removes its now-empty institution from the
visible catalogue; generic account deletion preserves its institution, matching
the corresponding legacy operations.

## Official M-Rating and display facts

V18 stores immutable import evidence and per-channel official observations.
V23 distinguishes institutional observations from channel observations: an
unrated channel does not inherit its institution's rank. Latest-period selection,
category mapping, ties, casefold and NULL handling are checked against unchanged
`app.m_rating` code. A repeated correlation UUID returns the first import result
without making another network request.

The production source uses bounded pinned HTTPS with host, redirect, DNS/IP,
TLS, byte and total deadline validation. Set
`MRANKED_ADMIN_OFFICIAL_RATING_ENABLED=false` for an offline rehearsal. Failed
fetches expose a fixed error classification; arbitrary upstream error strings
and credentials are not returned. Imported status comes from the original
`m_rating_last_*` state or a committed native import, not an inferred observation
date.

V25 exposes a narrow `legacy_account_presentation(uuid)` function only to
`api_write_admin`. Original access-mode labels are retained separately from the
canonical collector protocol and bound to the exact current source row/batch.
The bridge backfills this safe representation from an unchanged accepted source
on replay. Unknown labels use a safe protocol equivalent. Original error text
is represented by a fixed code, presence, length and digest; no raw error is
sent to the browser. Raw grants remain denied.

Storage values describe the current deployment. Failed, slow or oversized
filesystem walks produce unknown rather than a partial size. MAX status counts
the visible accounts and their current native identities. Provider readiness is
explicit deployment configuration and does not infer credential values.

## Verification

Run the self-provisioning required gate from the repository root:

```sh
python -m migration.integration.run
```

It provisions its own PostgreSQL/Redis project, installs the final schema directly,
exercises dedicated-role and HTTP security tests, and
removes only its own databases/volumes. Java oracle launchers use the runner's
Python interpreter, including CI without a local `.venv`.

Relevant test classes include `CatalogPostgresIntegrationTest`,
`CatalogHttpPostgresIntegrationTest`, `LegacyFormPostgresIntegrationTest`,
`OfficialRatingContextPostgresIntegrationTest`, `OfficialRatingParserTest`,
`HttpOfficialRatingSourceTest` and the V25 presentation tests. Evidence from a run is local and is not committed; a historical green run is
not acceptance for a later schema or source change.
