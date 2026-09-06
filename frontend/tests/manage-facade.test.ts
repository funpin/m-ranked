import assert from "node:assert/strict";
import test from "node:test";
import { NextRequest } from "next/server";
import { submitManage } from "../lib/manage-facade";

const csrf = "unit-csrf";
const correlation = "11111111-2222-4333-8444-555555555555";
const authorization = `Basic ${Buffer.from("unit-user:unit-password").toString("base64")}`;
function request(path = "/manage/institutions", body?: string, extra: HeadersInit = {}): NextRequest {
  const headers = new Headers({ authorization, cookie: `MRANKED-MANAGE-CSRF=${csrf}`, "content-type": "application/x-www-form-urlencoded" });
  new Headers(extra).forEach((value, key) => headers.set(key, value));
  return new NextRequest(`https://m-ranked.test${path}`, { method: "POST", headers, body });
}
function server(command: (init: RequestInit) => Response | Promise<Response> = () => Response.json({ location: "/manage" }), roles = { canEdit: true, canDelete: true }) {
  const calls: { path: string; init: RequestInit }[] = [];
  const fetcher: typeof fetch = async (input, init = {}) => {
    const path = new URL(String(input)).pathname;
    calls.push({ path, init });
    assert.equal(init.redirect, "error"); assert.equal(init.cache, "no-store");
    return path.endsWith("/session") ? Response.json({ headerName: "X-XSRF-TOKEN", token: csrf, ...roles }) : command(init);
  };
  return { fetcher, calls };
}
const missing = (key: string) => ({ type: "missing", loc: ["body", key], msg: "Field required", input: null });
const invalidInteger = (scope: string, key: string, input: string) => ({ type: "int_parsing", loc: [scope, key], msg: "Input should be a valid integer, unable to parse string as an integer", input });

// Oracle: real FastAPI TestClient against a disposable SQLite database, 2026-09-05.
test("anonymous and invalid credentials precede missing forms and CSRF without reading the body", async () => {
  for (const [auth, detail] of [["", "Not authenticated"], ["Bearer secret", "Not authenticated"], ["Basic broken", "Invalid authentication credentials"], [authorization, "Неверный логин или пароль"]]) {
    const incoming = request("/manage/institutions/not-an-id", "", { authorization: auth });
    let calls = 0;
    const response = await submitManage(incoming, async () => { calls++; return Response.json({ detail: "upstream-secret" }, { status: 401 }); });
    assert.equal(response.status, 401); assert.equal(response.headers.get("www-authenticate"), "Basic");
    assert.deepEqual(await response.json(), { detail }); assert.equal(incoming.bodyUsed, false); assert.equal(calls, 1);
  }
});

test("all legacy actions preserve missing-field order, locations and null input", async () => {
  const cases: [string, string[]][] = [
    ["/manage/institutions", ["name", "csrf_token"]], ["/manage/channels", ["channel", "csrf_token"]],
    ["/manage/platform-accounts", ["institution_id", "platform", "reference", "csrf_token"]],
    ["/manage/institutions/1", ["name", "short_name", "csrf_token"]], ["/manage/institutions/1/accounts", ["csrf_token"]],
    ["/manage/m-rating/update", ["csrf_token"]], ["/manage/platform-accounts/1/native-id", ["native_id", "csrf_token"]],
    ...["channels", "platform-accounts"].flatMap(kind => ["enable", "disable", "delete"].map(operation => [`/manage/${kind}/1/${operation}`, ["csrf_token"]] as [string, string[]])),
  ];
  for (const [path, keys] of cases) {
    const upstream = server(); const response = await submitManage(request(path), upstream.fetcher);
    assert.equal(response.status, 422, path); assert.deepEqual(await response.json(), { detail: keys.map(missing) });
    assert.equal(upstream.calls.length, 1); assert.equal(response.headers.get("cache-control"), "no-store");
  }
});

test("path validation precedes body validation and accepts Python integral spellings", async () => {
  const upstream = server();
  const failed = await submitManage(request("/manage/institutions/abc"), upstream.fetcher);
  assert.equal(failed.status, 422);
  assert.deepEqual(await failed.json(), { detail: [invalidInteger("path", "institution_id", "abc"), missing("name"), missing("short_name"), missing("csrf_token")] });
  for (const raw of ["+01", "1.00", "1_0", "%201%20"]) {
    const positive = server(init => { assert.match(JSON.parse(String(init.body)).path, /^\/manage\/institutions\/(?:1|10)$/); return Response.json({ location: "/manage" }); });
    assert.equal((await submitManage(request(`/manage/institutions/${raw}`, `name=a&short_name=b&csrf_token=${csrf}`), positive.fetcher)).status, 303);
  }
});

test("integer form validation runs before CSRF and retains legacy input", async () => {
  for (const value of ["abc", "", "1e0", "1.1"]) {
    const response = await submitManage(request("/manage/platform-accounts", `institution_id=${value}&platform=max&reference=a&csrf_token=wrong`), server().fetcher);
    assert.equal(response.status, 422); assert.deepEqual(await response.json(), { detail: [invalidInteger("body", "institution_id", value)] });
  }
});

test("empty strings are present fields, then CSRF is checked without echoing tokens", async () => {
  for (const body of ["name=&short_name=&csrf_token=wrong", "name=a&short_name=b&csrf_token=", "name=a&short_name=b&csrf_token=%F0%9F%98%80"]) {
    const response = await submitManage(request("/manage/institutions/1", body), server().fetcher);
    assert.equal(response.status, 403); assert.deepEqual(await response.json(), { detail: "Недействительный защитный токен" });
  }
  const response = await submitManage(request("/manage/institutions", `name=a&csrf_token=${csrf}`, { cookie: "MRANKED-MANAGE-CSRF=%F0%9F%98%80" }), server().fetcher);
  assert.equal(response.status, 403);
});

test("last duplicated scalar including CSRF and correlation wins; only form fields and trusted headers cross the boundary", async () => {
  const upstream = server(init => {
    const headers = new Headers(init.headers);
    assert.equal(headers.get("X-XSRF-TOKEN"), csrf); assert.equal(headers.get("X-Correlation-Id"), correlation);
    assert.equal(headers.get("cookie"), `XSRF-TOKEN=${csrf}`); assert.equal(headers.get("authorization"), authorization);
    for (const key of ["x-mranked-can-edit", "x-mranked-can-delete", "host", "x-secret"]) assert.equal(headers.get(key), null);
    assert.deepEqual(JSON.parse(String(init.body)), { path: "/manage/institutions", fields: { name: "last", short_name: "", expected_row_version: "7", expected_account_versions: "{}" } });
    return Response.json({ location: "/manage?platform_status=institution-added&institution_id=123" });
  });
  const incoming = request("/manage/institutions", `name=first&name=last&short_name=&csrf_token=wrong&csrf_token=${csrf}&correlation_id=bad&correlation_id=${correlation}&expected_row_version=7&expected_account_versions=%7B%7D&__proto__=bad&unknown_secret=hidden`, { cookie: `session=never-forward; MRANKED-MANAGE-CSRF=${csrf}`, "x-mranked-can-edit": "true", "x-secret": "never-forward" });
  const response = await submitManage(incoming, upstream.fetcher);
  assert.equal(response.status, 303); assert.equal(response.headers.get("location"), "/manage?platform_status=institution-added&institution_id=123");
  assert.equal(response.headers.get("referrer-policy"), "same-origin");
  assert.equal(response.headers.get("set-cookie"), null); assert.equal(upstream.calls.length, 2);
});

test("last empty duplicate CSRF and invalid correlation cannot execute a command", async () => {
  for (const [suffix, status] of [[`csrf_token=${csrf}&csrf_token=`, 403], [`csrf_token=${csrf}&correlation_id=${correlation}&correlation_id=bad`, 400]] as const) {
    const upstream = server(); assert.equal((await submitManage(request("/manage/institutions", `name=a&${suffix}`), upstream.fetcher)).status, status);
    assert.equal(upstream.calls.length, 1);
  }
});

test("zero/negative IDs are missing resources after CSRF; unsupported routes remain framework 404", async () => {
  for (const [path, detail] of [["/manage/institutions/0", "Вуз не найден"], ["/manage/channels/-1/enable", "Канал не найден"], ["/manage/platform-accounts/0/delete", "Аккаунт не найден"]]) {
    const upstream = server(); const response = await submitManage(request(path, `name=a&short_name=b&csrf_token=${csrf}`), upstream.fetcher);
    assert.equal(response.status, 404); assert.deepEqual(await response.json(), { detail }); assert.equal(upstream.calls.length, 1);
  }
  for (const path of ["/manage/channels/1/native-id", "/manage/institutions/1/delete", "/manage/nope", "/manage/institutions/a%2Fb"]) {
    const upstream = server(); const response = await submitManage(request(path), upstream.fetcher);
    assert.equal(response.status, 404); assert.deepEqual(await response.json(), { detail: "Not Found" }); assert.equal(upstream.calls.length, 0);
  }
});

test("viewer and non-admin delete cannot bypass RBAC using trusted-looking request headers", async () => {
  for (const [path, roles] of [["/manage/institutions", { canEdit: false, canDelete: false }], ["/manage/channels/1/delete", { canEdit: true, canDelete: false }]] as const) {
    const upstream = server(undefined, roles);
    const response = await submitManage(request(path, `name=a&csrf_token=${csrf}`, { "x-mranked-can-edit": "true", "x-mranked-can-delete": "true" }), upstream.fetcher);
    assert.equal(response.status, 403); assert.equal(upstream.calls.length, 1);
  }
});

test("same-origin, exact content type and announced size safeguards execute no command", async () => {
  for (const [headers, expected] of [[{ origin: "https://attacker.test" }, 403], [{ "content-type": "application/x-www-form-urlencoded-evil" }, 415], [{ "content-length": "196609" }, 413]] as [HeadersInit, number][]) {
    const upstream = server(); assert.equal((await submitManage(request(undefined, "name=a", headers), upstream.fetcher)).status, expected); assert.equal(upstream.calls.length, 1);
  }
});

test("same-origin forms retain the browser Host across NextURL loopback normalization", async () => {
  for (const host of ["127.0.0.1:18099", "[::1]:18099", "localhost:18099"]) {
    const upstream = server();
    const incoming = new NextRequest(`http://${host}/manage/institutions`, { method: "POST",
      headers: { ...Object.fromEntries(request().headers), host, origin: `http://${host}` },
      body: `name=a&csrf_token=${csrf}` });
    assert.equal(incoming.nextUrl.hostname, "localhost");
    const response = await submitManage(incoming, upstream.fetcher);
    assert.equal(response.status, 303, host); assert.equal(upstream.calls.length, 2);
  }
});

test("Host validation rejects cross-origin forms and ignores forged forwarded authorities", async () => {
  for (const [host, origin] of [["127.0.0.1:18099", "http://localhost:18099"],
    ["127.0.0.1:18099", "http://127.0.0.1:18100"], ["127.0.0.1:18099", "https://127.0.0.1:18099"],
    ["127.0.0.1:18099", "null"], ["m-ranked.test,attacker.test", "http://attacker.test"],
    ["m-ranked.test@attacker.test", "http://attacker.test"], ["attacker.test/", "http://attacker.test"]]) {
    const upstream = server();
    const incoming = new NextRequest("http://127.0.0.1:18099/manage/institutions", { method: "POST",
      headers: { ...Object.fromEntries(request().headers), host, origin, "x-forwarded-host": origin.replace(/^https?:\/\//, "") },
      body: `name=a&csrf_token=${csrf}` });
    assert.equal((await submitManage(incoming, upstream.fetcher)).status, 403, `${host} / ${origin}`);
    assert.equal(upstream.calls.length, 1); assert.equal(incoming.bodyUsed, false);
  }
});

test("unannounced oversized stream is cancelled and read errors are sanitized", async () => {
  for (const throws of [false, true]) {
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({ pull(controller) { if (throws) controller.error(new Error("secret stream failure")); else controller.enqueue(new Uint8Array(100_000)); }, cancel() { cancelled = true; } });
    const incoming = new NextRequest("https://m-ranked.test/manage/institutions", { method: "POST", headers: request().headers, body: stream, duplex: "half" } as ConstructorParameters<typeof NextRequest>[1]);
    const upstream = server(); const response = await submitManage(incoming, upstream.fetcher);
    assert.equal(response.status, throws ? 400 : 413); assert.equal(cancelled, !throws); assert.equal(upstream.calls.length, 1); assert.doesNotMatch(await response.text(), /secret/);
  }
});

test("upstream errors are fixed allowlisted values and never reveal exception details", async () => {
  for (const [status, type, detail, expected] of [
    [400, "urn:m-ranked:problem:legacy-form", "MAX chat_id должен быть числом", "MAX chat_id должен быть числом"],
    [400, "urn:m-ranked:problem:legacy-form", "password=secret", "Не удалось выполнить команду"],
    [400, "urn:m-ranked:problem:invalid-request", "Укажите название вуза", "Не удалось выполнить команду"],
    [500, "urn:m-ranked:problem:internal-error", "database-password=secret", "Не удалось выполнить команду"],
    [404, "anything", "database-secret", "Вуз не найден"],
    [409, "anything", "database-secret", "Данные изменились. Обновите страницу и повторите действие."],
  ] as const) {
    const response = await submitManage(request(undefined, `name=a&csrf_token=${csrf}`), server(() => Response.json({ type, detail }, { status })).fetcher);
    assert.equal(response.status, status); assert.deepEqual(await response.json(), { detail: expected });
  }
});

test("malformed/oversized session, fetch failure and open redirects fail closed", async () => {
  for (const fetcher of [async () => Response.json({ token: "secret" }), async () => new Response("x".repeat(20_000))])
    assert.equal((await submitManage(request(), fetcher)).status, 502);
  assert.equal((await submitManage(request(), async () => { throw new Error("credential=secret"); })).status, 503);
  for (const location of ["https://evil.test/manage", "//evil.test/manage", "/manage?token=secret%0aLocation:evil", "/manage/other"])
    assert.equal((await submitManage(request(undefined, `name=a&csrf_token=${csrf}`), server(() => Response.json({ location })).fetcher)).status, 502);
});
