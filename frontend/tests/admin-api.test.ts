import assert from "node:assert/strict";
import test from "node:test";
import {
  AdminApiError,
  createAdminSession,
  withConflictRefresh,
} from "../lib/admin-api";

const UUID = "11111111-1111-4111-8111-111111111111";
const ACCOUNT_UUID = "22222222-2222-4222-8222-222222222222";

function csrfResponse() {
  return Response.json({ headerName: "X-XSRF-TOKEN", parameterName: "_csrf", token: "csrf-value" });
}

test("admin session constructs bounded same-origin no-store requests", async () => {
  const seen: Array<{ url: string; init: RequestInit }> = [];
  const session = createAdminSession(
    { username: "operator", password: "top-secret" },
    {
      origin: "https://m-ranked.example",
      fetcher: async (input, init) => {
        seen.push({ url: String(input), init: init ?? {} });
        if (seen.length === 1) return csrfResponse();
        if (seen.length === 2) return Response.json({ items: [] });
        return Response.json({ job: { jobId: UUID }, accountResults: [], accountResultsTruncated: false });
      },
    },
  );

  await session.initialize();
  await session.jobs({ platform: "telegram", status: "failed", limit: 999 });
  await session.job(UUID, 999);

  assert.equal(seen[0]!.url, "https://m-ranked.example/api/v1/admin/csrf");
  assert.equal(seen[1]!.url, "https://m-ranked.example/api/v1/admin/jobs?platform=telegram&status=failed&limit=100");
  assert.equal(seen[2]!.url, `https://m-ranked.example/api/v1/admin/jobs/${UUID}?accountResultLimit=200`);
  for (const request of seen) {
    assert.equal(request.init.cache, "no-store");
    assert.equal(request.init.credentials, "same-origin");
    assert.equal(request.init.redirect, "error");
    assert.equal(request.init.referrerPolicy, "no-referrer");
    assert.ok(new Headers(request.init.headers).get("Authorization")?.startsWith("Basic "));
    assert.ok(!request.url.includes("operator"));
    assert.ok(!request.url.includes("top-secret"));
  }
});

test("admin credentials remain in a closable in-memory session and never touch web storage", async () => {
  const previousLocal = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  const previousSession = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
  const forbidden = new Proxy({}, { get() { throw new Error("storage access is forbidden"); } });
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: forbidden });
  Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: forbidden });
  try {
    const session = createAdminSession(
      { username: "operator", password: "top-secret" },
      { origin: "https://m-ranked.example", fetcher: async () => csrfResponse() },
    );
    await session.initialize();
    assert.equal(JSON.stringify(session), "{}");
    session.close();
    await assert.rejects(
      () => session.jobs(),
      (error: unknown) => error instanceof AdminApiError && error.status === 401,
    );
  } finally {
    if (previousLocal) Object.defineProperty(globalThis, "localStorage", previousLocal);
    else delete (globalThis as { localStorage?: unknown }).localStorage;
    if (previousSession) Object.defineProperty(globalThis, "sessionStorage", previousSession);
    else delete (globalThis as { sessionStorage?: unknown }).sessionStorage;
  }
});

test("account mutation sends CSRF, correlation ID and required optimistic version", async () => {
  const seen: Array<{ url: string; init: RequestInit }> = [];
  const session = createAdminSession(
    { username: "editor", password: "secret" },
    {
      origin: "https://m-ranked.example",
      randomUuid: () => UUID,
      fetcher: async (input, init) => {
        seen.push({ url: String(input), init: init ?? {} });
        if (seen.length === 1) return csrfResponse();
        return Response.json({
          account: { accountId: ACCOUNT_UUID, platform: "telegram", enabled: false, rowVersion: 8, updatedAt: "2026-09-03T10:00:00Z" },
          changed: true,
          datasetRevision: 18,
          correlationId: UUID,
          outcome: "updated",
        });
      },
    },
  );

  await session.initialize();
  await session.setAccountEnabled({ accountId: ACCOUNT_UUID, enabled: false, expectedRowVersion: 7 });

  const mutation = seen[1]!;
  assert.equal(mutation.url, `https://m-ranked.example/api/v1/admin/platform-accounts/${ACCOUNT_UUID}/enabled`);
  assert.equal(mutation.init.method, "PUT");
  const headers = new Headers(mutation.init.headers);
  assert.equal(headers.get("X-XSRF-TOKEN"), "csrf-value");
  assert.equal(headers.get("X-Correlation-Id"), UUID);
  assert.deepEqual(JSON.parse(String(mutation.init.body)), { enabled: false, expectedRowVersion: 7 });
});

test("account lookup reads the minimal state through a same-origin no-store GET", async () => {
  const seen: Array<{ url: string; init: RequestInit }> = [];
  const expected = {
    accountId: ACCOUNT_UUID,
    platform: "telegram" as const,
    enabled: true,
    rowVersion: 7,
    updatedAt: "2026-09-03T10:00:00Z",
  };
  const session = createAdminSession(
    { username: "viewer", password: "secret" },
    {
      origin: "https://m-ranked.example",
      fetcher: async (input, init) => {
        seen.push({ url: String(input), init: init ?? {} });
        if (seen.length === 1) return csrfResponse();
        return Response.json(expected, {
          headers: { "Cache-Control": "no-store" },
        });
      },
    },
  );

  await session.initialize();
  assert.deepEqual(await session.account(` ${ACCOUNT_UUID.toUpperCase()} `), expected);
  assert.equal(
    seen[1]!.url,
    `https://m-ranked.example/api/v1/admin/platform-accounts/${ACCOUNT_UUID}`,
  );
  assert.equal(seen[1]!.init.method, "GET");
  assert.equal(seen[1]!.init.cache, "no-store");
  assert.equal(seen[1]!.init.credentials, "same-origin");
  assert.equal(new Headers(seen[1]!.init.headers).get("X-XSRF-TOKEN"), null);
});

test("account lookup rejects an unsafe or mismatched optimistic version response", async () => {
  const session = createAdminSession(
    { username: "viewer", password: "secret" },
    {
      origin: "https://m-ranked.example",
      fetcher: async (input) => String(input).endsWith("/csrf")
        ? csrfResponse()
        : Response.json({
            accountId: UUID,
            platform: "telegram",
            enabled: true,
            rowVersion: Number.MAX_SAFE_INTEGER + 1,
            updatedAt: "2026-09-03T10:00:00Z",
          }),
    },
  );

  await session.initialize();
  await assert.rejects(
    () => session.account(ACCOUNT_UUID),
    (error: unknown) => error instanceof AdminApiError && error.status === 502,
  );
});

test("account mutation fails closed until the CSRF contract is initialized", async () => {
  let calls = 0;
  const session = createAdminSession(
    { username: "editor", password: "secret" },
    { origin: "https://m-ranked.example", fetcher: async () => { calls += 1; return Response.json({}); }, randomUuid: () => UUID },
  );
  await assert.rejects(
    () => session.setAccountEnabled({ accountId: ACCOUNT_UUID, enabled: true, expectedRowVersion: 0 }),
    (error: unknown) => error instanceof AdminApiError && error.status === 403,
  );
  assert.equal(calls, 0);
});

test("conflict refresh runs once and preserves the RFC 9457 conflict", async () => {
  let refreshes = 0;
  const conflict = new AdminApiError(409, "conflict", { type: "urn:m-ranked:problem:optimistic-lock", status: 409 });
  await assert.rejects(
    () => withConflictRefresh(
      async () => { throw conflict; },
      async () => { refreshes += 1; },
    ),
    (error: unknown) => error === conflict,
  );
  assert.equal(refreshes, 1);
});

test("admin URL and numeric bounds reject identifier injection", async () => {
  let calls = 0;
  assert.throws(
    () => createAdminSession(
      { username: "operator", password: "secret" },
      {
        origin: "https://m-ranked.example/path?ignored=no",
        fetcher: async () => { calls += 1; return csrfResponse(); },
      },
    ),
    AdminApiError,
  );
  assert.equal(calls, 0);

  const validSession = createAdminSession(
    { username: "operator", password: "secret" },
    { origin: "https://m-ranked.example", fetcher: async () => Response.json({}) },
  );
  await assert.rejects(() => validSession.job("../../overview"), AdminApiError);
  await assert.rejects(() => validSession.account("../../overview"), AdminApiError);
  await assert.rejects(
    () => validSession.setAccountEnabled({ accountId: ACCOUNT_UUID, enabled: true, expectedRowVersion: -1 }),
    AdminApiError,
  );
});
