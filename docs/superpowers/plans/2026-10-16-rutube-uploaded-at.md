# Rutube upload date (`uploaded_at`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store Rutube `created_ts` as `ingest.publication.uploaded_at` on both databases, carried S1 → S2 by the transfer, plus a one-off backfill for videos outside the 30-day tracking window.

**Architecture:** A nullable column filled only for Rutube. The value rides alongside — never inside — the snapshot fingerprints and `quality_flags`, so snapshot dedup and other platforms' transfer events stay byte-identical. The upsert keeps an existing date when a batch carries none.

**Tech Stack:** Python 3 (dataclasses, httpx, psycopg 3), PostgreSQL 18, pytest.

**Spec:** `docs/superpowers/specs/2026-10-16-rutube-uploaded-at-design.md`

## Global Constraints

- Column: `ingest.publication.uploaded_at timestamptz NULL`, migration `db/migrations/0083_publication_uploaded_at.sql`, `SET LOCAL lock_timeout = '5s'`, no default (catalog-only change).
- `uploaded_at` must not enter `evidence`, `semantic_state`, `source` or `quality_flags`.
- Transfer key `uploadedAt` is emitted only when the date is set; decoder uses `.get("uploadedAt")`.
- Upsert: `uploaded_at = COALESCE(excluded.uploaded_at, current.uploaded_at)`, and the column is part of the `IS DISTINCT FROM` change check.
- A missing or unparseable `created_ts` yields `None`, never a rejected video or batch.
- Never commit addresses, ports or keys; no Claude co-author line in commits.
- AGENTS.md: measure before/after on the local production copy; no regressions.

## Review Focus

1. Batch without `uploadedAt` (old sealed envelope, refresh path) arriving after the date was stored → the date stays.
2. Telegram/VK/MAX batches after the change → event JSON, `eventId` and snapshot fingerprints identical to before.
3. `created_ts` with `Z`, with offset, naive, garbage, or absent → aware UTC datetime or `None`, no exception.
4. Re-ingesting an unchanged Rutube batch → no `UPDATE` of `ingest.publication` (RETURNING is empty).
5. Backfill run twice, or with 404 videos → second run writes nothing; 404s are skipped and counted.

---

### Task 1: Collector reads `created_ts`

**Files:**
- Modify: `collector_runtime/rutube.py` (`RutubeVideo`, `videos()`, `video()`, new `optional_rutube_datetime`)
- Test: `tests/test_rutube.py`

**Interfaces:**
- Produces: `RutubeVideo.uploaded_at: datetime | None = None` (last field); `optional_rutube_datetime(value: Any) -> datetime | None`.

- [ ] **Step 1: Failing tests**

```python
def test_rutube_video_lookup_keeps_upload_time_apart_from_publication():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "video-1", "title": "V",
            "created_ts": "2026-07-31T21:00:00",
            "publication_ts": "2026-08-01T08:00:00",
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await RutubeClient("https://rutube.ru/api", http).video("video-1")

    video = asyncio.run(run())
    assert video.published_at == datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)
    assert video.uploaded_at == datetime(2026, 7, 31, 21, 0, tzinfo=timezone.utc)


def test_rutube_channel_listing_reads_upload_time_and_tolerates_bad_values():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"has_next": False, "results": [
            {"id": "a", "created_ts": "2026-07-30T10:00:00Z", "publication_ts": "2026-08-02T10:00:00Z"},
            {"id": "b", "created_ts": "not a date", "publication_ts": "2026-08-02T11:00:00Z"},
            {"id": "c", "publication_ts": "2026-08-02T12:00:00+03:00"},
        ]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await RutubeClient("https://rutube.ru/api", http).videos(5)

    _channel, videos = asyncio.run(run())
    by_id = {video.id: video for video in videos}
    assert by_id["a"].uploaded_at == datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)
    assert by_id["b"].uploaded_at is None
    assert by_id["c"].uploaded_at is None
```

- [ ] **Step 2:** `pytest tests/test_rutube.py -k upload -v` → FAIL (`RutubeVideo` has no `uploaded_at`).
- [ ] **Step 3: Implement**

```python
@dataclass(frozen=True)
class RutubeVideo:
    id: str
    title: str
    published_at: datetime
    views: int | None
    url: str
    raw: dict[str, Any]
    # created_ts: М-Рейтинг считает видео за месяц по дате загрузки, а не выхода.
    uploaded_at: datetime | None = None


def optional_rutube_datetime(value: Any) -> datetime | None:
    """Parse an optional RUTUBE timestamp; a bad value must not drop the video."""
    if not value:
        return None
    try:
        return parse_rutube_datetime(str(value))
    except ValueError:
        return None
```

In `videos()` and `video()` pass `uploaded_at=optional_rutube_datetime(item.get("created_ts"))` (resp. `payload.get(...)`).

- [ ] **Step 4:** `pytest tests/test_rutube.py -v` → PASS.
- [ ] **Step 5:** commit `feat(rutube): read the video upload time (created_ts)`.

### Task 2: Raw and canonical publication carry the date

**Files:**
- Modify: `collector_target/model.py` (`RawPublication`, `CanonicalPublication`), `collector_target/normalize.py`, `collector_target/platforms/rutube.py`
- Test: `tests/test_target_collectors.py`

**Interfaces:**
- Consumes: `RutubeVideo.uploaded_at`.
- Produces: `RawPublication.uploaded_at: datetime | None = None` (last field); `CanonicalPublication.uploaded_at: datetime | None = None` (last field, after `snapshot`).

- [ ] **Step 1: Failing tests**

```python
def test_rutube_batch_carries_upload_time_outside_snapshot_fingerprints() -> None:
    target = account(Platform.RUTUBE)
    base = RutubeVideo("video-1", "Video", NOW - timedelta(minutes=5), 3,
                       "https://rutube.ru/video/video-1/", {})
    uploaded = replace(base, uploaded_at=NOW - timedelta(days=40))

    def normalized(video):
        raw = rutube_batch(
            account=target,
            channel=RutubeChannel(5, "RUTUBE", "https://rutube.ru/channel/5/"),
            videos=(video,), metrics={"video-1": RutubeVideoMetrics(1, 0, {})},
            observed_at=NOW, collected_at=NOW, subscriber_count=None,
        )
        assert raw.publications[0].uploaded_at == video.uploaded_at
        return CanonicalNormalizer().normalize(raw, context(Platform.RUTUBE)).publications[0]

    without, with_date = normalized(base), normalized(uploaded)
    assert without.uploaded_at is None
    assert with_date.uploaded_at == NOW - timedelta(days=40)
    assert with_date.quality_flags == without.quality_flags
    assert with_date.snapshot.semantic_fingerprint == without.snapshot.semantic_fingerprint
    assert with_date.snapshot.source_fingerprint == without.snapshot.source_fingerprint
```

(Import `replace` from `dataclasses` and `CanonicalNormalizer` if the module lacks them.)

- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement.** Add the two fields. In `rutube_batch` pass `uploaded_at=video.uploaded_at`. In `CanonicalNormalizer` build the canonical publication with
  `uploaded_at=utc(raw.uploaded_at, "uploaded_at") if raw.uploaded_at is not None else None` — nothing added to `evidence`/`semantic_state`.
- [ ] **Step 4:** `pytest tests/test_target_collectors.py tests/test_transfer.py -q` → PASS.
- [ ] **Step 5:** commit `feat(collector): carry the Rutube upload time on canonical publications`.

### Task 3: Transfer S1 → S2

**Files:**
- Modify: `collector_target/transfer.py` (`_batch_dict`, `_decode_batch`)
- Test: `tests/test_transfer.py`

- [ ] **Step 1: Failing tests**

```python
def test_upload_time_round_trips_and_is_absent_when_unknown() -> None:
    batch = _batch()
    publication = batch.publications[0]
    assert "uploadedAt" not in canonical_event(batch)["batch"]["publications"][0]
    dated = replace(batch, publications=(replace(
        publication, uploaded_at=datetime(2026, 7, 31, 21, tzinfo=timezone.utc),
    ),))
    event = canonical_event(dated)
    assert event["batch"]["publications"][0]["uploadedAt"] == "2026-07-31T21:00:00Z"
    assert decode_events(with_cursor(seal_batch(dated, "server-1/default"), 1)) == (dated,)


def test_publication_without_upload_time_keeps_the_previous_event_shape() -> None:
    # Other platforms keep the exact key set, hence their eventId/semanticHash.
    assert set(canonical_event(_batch())["batch"]["publications"][0]) == {
        "id", "accountId", "contentGroupId", "externalId", "sourceExternalId",
        "identities", "publicUrl", "publishedAt", "discoveredAt",
        "publicationType", "isRepost", "historyCompleteness",
        "syntheticBaselineAllowed", "qualityFlags", "snapshot",
    }
```

(Import `canonical_event` from `collector_target.transfer`.)

- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement.** In `_batch_dict` build each publication dict, then `if item.uploaded_at is not None: entry["uploadedAt"] = _iso(item.uploaded_at)`. In `_decode_batch` pass `uploaded_at=_parse_time(item["uploadedAt"]) if item.get("uploadedAt") is not None else None` as keyword after the snapshot.
- [ ] **Step 4:** `pytest tests/test_transfer.py tests/test_transfer_ingest.py -q` → PASS.
- [ ] **Step 5:** commit `feat(transfer): carry uploadedAt for Rutube publications`.

### Task 4: Migration and upsert

**Files:**
- Create: `db/migrations/0083_publication_uploaded_at.sql`
- Modify: `collector_target/repository.py` (publication upsert ~1535–1650)
- Test: `tests/test_target_collectors_postgres.py` (new PG test; skips without `MRANKED_TEST_POSTGRES_DSN`)

- [ ] **Step 1: Migration**

```sql
-- 0083 — дата загрузки видео (Rutube created_ts) рядом с датой публикации.
-- ...why, see spec...
BEGIN;
SET LOCAL lock_timeout = '5s';
ALTER TABLE ingest.publication ADD COLUMN uploaded_at timestamp with time zone;
COMMENT ON COLUMN ingest.publication.uploaded_at IS '...';
COMMIT;
```

- [ ] **Step 2: Failing PG test** — create institution + Rutube account, persist a normalized Rutube batch with `uploaded_at`, assert the column; persist a later batch for the same video without the date, assert it is kept; persist the dated batch again and assert `persist_account_batch` changed no publication row (`SELECT xmin` unchanged). Cleanup like the neighbouring tests (`session_replication_role=replica`, delete by account).
- [ ] **Step 3:** run against a disposable PG with all migrations → FAIL (column absent / not written).
- [ ] **Step 4: Implement.** Add `"uploaded_at": _iso_or_none(item.uploaded_at)` to `publication_input`, `uploaded_at timestamptz` to the recordset, the column to INSERT/SELECT, `uploaded_at=COALESCE(excluded.uploaded_at, current.uploaded_at)` to SET, and `current.uploaded_at` / `COALESCE(excluded.uploaded_at, current.uploaded_at)` to both `ROW(...)` lists.
- [ ] **Step 5:** PG test PASS; full suite compared to `main` (16 pre-existing failures).
- [ ] **Step 6:** commit `feat(db): ingest.publication.uploaded_at for Rutube upload dates`.

### Task 5: Backfill tool

**Files:**
- Create: `collector_target/rutube_upload_backfill.py`
- Test: `tests/test_rutube_upload_backfill.py`

**Interfaces:**
- `backfill_sql(rows: Iterable[tuple[str, datetime]], chunk: int = 500) -> str` — pure.
- `async fetch_upload_times(client: RutubeClient, ids: Iterable[str], concurrency: int = 4) -> tuple[list[tuple[str, datetime]], Counter]`.
- `main(argv)`: ids from a file or stdin (one per line, blanks/dupes ignored) → SQL on stdout, counts on stderr.

- [ ] **Step 1: Failing tests** — `backfill_sql` quotes ids as SQL literals, emits `BEGIN;…COMMIT;`, `AND p.uploaded_at IS NULL`, `a.platform='rutube'`, one `UPDATE` per chunk; rejects ids outside `[0-9A-Za-z_-]`. `fetch_upload_times` with `httpx.MockTransport`: 200 → row, 404 → counted `missing`, no `created_ts` → counted `no_created_ts`, 500 → counted `error`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5: Apply on the local copy** inside `BEGIN … ROLLBACK` to check the UPDATE count.
- [ ] **Step 6:** commit `feat(rutube): one-off backfill of upload dates`.

### Task 6: Runbook, measurements, PR

- [ ] `operations/runbooks/DEPLOY.md`: section for `0083` — order (both DBs → S2 ingest → S1 Rutube collector → backfill), check query, rollback.
- [ ] Measure on `mranked_prod_20261013` (before = main code/schema, after = branch): migration time; EXPLAIN ANALYZE of the old vs new upsert for 100 Rutube publications (rolled back); `pg_total_relation_size('ingest.publication')` before/after backfill; transfer event size of a 100-video Rutube batch; the forecast read (videos per account per Moscow month by `uploaded_at`). Record in the PR body.
- [ ] Push, open PR, bind with ccd_pr.
