import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, createApiClient } from "../lib/api";

const overviewPayload = {
  items: [],
  nextCursor: null,
  datasetRevision: 17,
  asOf: "2026-09-03T09:00:00Z",
};

test("API client revalidates a cached response with If-None-Match", async () => {
  const requests: RequestInit[] = [];
  let call = 0;
  const client = createApiClient({
    baseUrl: "https://api.example.test",
    fetcher: async (_input, init) => {
      requests.push(init ?? {});
      call += 1;
      if (call === 1) {
        return Response.json(overviewPayload, { headers: { ETag: '"revision-17"' } });
      }
      return new Response(null, { status: 304, headers: { ETag: '"revision-17"' } });
    },
  });

  const first = await client.overview({ platform: "telegram", period: "1d" });
  const second = await client.overview({ platform: "telegram", period: "1d" });

  assert.deepEqual(first, overviewPayload);
  assert.strictEqual(second, first);
  const headers = new Headers(requests[1]?.headers);
  assert.equal(headers.get("If-None-Match"), '"revision-17"');
  assert.equal(requests[1]?.cache, "no-store");
});

test("API client keeps cache keys distinct across query parameters", async () => {
  const seenUrls: string[] = [];
  const client = createApiClient({
    baseUrl: "https://api.example.test/root/",
    fetcher: async (input) => {
      seenUrls.push(String(input));
      return Response.json(overviewPayload, { headers: { ETag: '"same"' } });
    },
  });

  await client.overview({
    platform: "telegram", period: "1d", q: " МГУ ",
    sort: "subscribers", direction: "asc",
  });
  await client.overview({ platform: "vk", period: "7d", q: "МГУ" });

  assert.equal(seenUrls.length, 2);
  assert.match(seenUrls[0]!, /^https:\/\/api\.example\.test\/api\/v1\/overview\?/);
  assert.ok(seenUrls[0]!.includes("platform=telegram"));
  assert.ok(seenUrls[0]!.includes("q=%D0%9C%D0%93%D0%A3"));
  assert.ok(seenUrls[0]!.includes("sort=subscribers"));
  assert.ok(seenUrls[0]!.includes("direction=asc"));
  assert.ok(seenUrls[1]!.includes("platform=vk"));
});

test("API client exposes RFC 9457 failures without masking status", async () => {
  const client = createApiClient({
    baseUrl: "https://api.example.test",
    fetcher: async () => Response.json(
      { type: "about:blank", title: "Not Found", status: 404, detail: "Unknown institution" },
      { status: 404, headers: { "content-type": "application/problem+json" } },
    ),
  });

  await assert.rejects(
    () => client.institution(999, "telegram", "30d"),
    (error: unknown) => error instanceof ApiError
      && error.status === 404
      && error.message === "Unknown institution"
      && error.problem?.title === "Not Found",
  );
});

test("publication compatibility routes send the correct legacyType", async () => {
  const seenUrls: string[] = [];
  const client = createApiClient({
    baseUrl: "https://api.example.test",
    fetcher: async (input) => {
      seenUrls.push(String(input));
      return Response.json({ legacyId: 31 });
    },
  });

  await client.publication(31, "posts");
  await client.publication(44, "platform_posts");

  assert.equal(seenUrls[0], "https://api.example.test/api/v1/publications/31?legacyType=posts");
  assert.equal(seenUrls[1], "https://api.example.test/api/v1/publications/44?legacyType=platform_posts");
});

test("account compatibility routes send the correct legacyType", async () => {
  const seenUrls: string[] = [];
  const client = createApiClient({
    baseUrl: "https://api.example.test",
    fetcher: async (input) => {
      seenUrls.push(String(input));
      return Response.json({ legacyId: 12 });
    },
  });

  await client.account(12, "channels");
  await client.account(27, "platform_accounts");

  assert.equal(seenUrls[0], "https://api.example.test/api/v1/accounts/12?legacyType=channels");
  assert.equal(seenUrls[1], "https://api.example.test/api/v1/accounts/27?legacyType=platform_accounts");
});

test("comparison client sends the fixed-cohort contract without camel-case drift", async () => {
  let seenUrl = "";
  const client = createApiClient({
    baseUrl: "https://api.example.test",
    fetcher: async (input) => {
      seenUrl = String(input);
      return Response.json({ series: [] });
    },
  });

  await client.comparison({
    platform: "vk",
    horizonHours: 168,
    includePartial: true,
    metric: "shares",
    aggregation: "sum",
    institutionLimit: 500,
    institutions: [91, 7, 34],
  });

  const url = new URL(seenUrl);
  assert.equal(url.pathname, "/api/v1/compare");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    aggregation: "sum",
    horizonHours: "168",
    includePartial: "true",
    institutionLimit: "50",
    institutions: "34",
    metric: "shares",
    platform: "vk",
  });
  assert.deepEqual(url.searchParams.getAll("institutions"), ["91", "7", "34"]);
});

test("comparison client preserves repeated Telegram channel IDs in request order", async () => {
  let seenUrl = "";
  const client = createApiClient({
    baseUrl: "https://api.example.test",
    fetcher: async (input) => {
      seenUrl = String(input);
      return Response.json({ series: [] });
    },
  });

  await client.comparison({
    platform: "telegram",
    horizonHours: 72,
    includePartial: false,
    metric: "reactions",
    aggregation: "median",
    channels: [920002, 920001],
  });

  const url = new URL(seenUrl);
  assert.deepEqual(url.searchParams.getAll("channels"), ["920002", "920001"]);
  assert.equal(url.searchParams.has("institutions"), false);
});

test("comparison client deduplicates relevant IDs and ignores the other legacy namespace", async () => {
  let calls = 0;
  const seenUrls: string[] = [];
  const client = createApiClient({
    baseUrl: "https://api.example.test",
    fetcher: async (input) => {
      calls += 1;
      seenUrls.push(String(input));
      return Response.json({ series: [] });
    },
  });

  await client.comparison({
    platform: "telegram",
    horizonHours: 72,
    includePartial: false,
    metric: "reactions",
    aggregation: "median",
    channels: [7, 7, 9],
    institutions: [91],
  });
  await client.comparison({
    platform: "vk",
    horizonHours: 72,
    includePartial: false,
    metric: "reactions",
    aggregation: "median",
    channels: [7],
    institutions: [91, 91],
  });

  assert.deepEqual(new URL(seenUrls[0]!).searchParams.getAll("channels"), ["7", "9"]);
  assert.equal(new URL(seenUrls[0]!).searchParams.has("institutions"), false);
  assert.deepEqual(new URL(seenUrls[1]!).searchParams.getAll("institutions"), ["91"]);
  assert.equal(new URL(seenUrls[1]!).searchParams.has("channels"), false);
  assert.equal(calls, 2);
});

test("comparison client rejects invalid or excess relevant IDs without substitution", () => {
  let calls = 0;
  const client = createApiClient({
    baseUrl: "https://api.example.test",
    fetcher: async () => {
      calls += 1;
      return Response.json({ series: [] });
    },
  });

  assert.throws(
    () => client.comparison({
      platform: "telegram",
      horizonHours: 72,
      includePartial: false,
      metric: "reactions",
      aggregation: "median",
      channels: [0],
    }),
    /positive safe integers/,
  );
  assert.throws(
    () => client.comparison({
      platform: "telegram",
      horizonHours: 72,
      includePartial: false,
      metric: "reactions",
      aggregation: "median",
      channels: Array.from({ length: 51 }, (_, index) => index + 1),
    }),
    /between 1 and 50/,
  );
  assert.throws(
    () => client.comparison({
      platform: "telegram",
      horizonHours: 72,
      includePartial: false,
      metric: "reactions",
      aggregation: "median",
      channels: [],
    }),
    /between 1 and 50/,
  );
  assert.equal(calls, 0);
});

test("rating client sends the bounded legacy-activity contract", async () => {
  let seenUrl = "";
  const client = createApiClient({
    baseUrl: "https://api.example.test",
    fetcher: async (input) => {
      seenUrl = String(input);
      return Response.json({ entities: [], publications: [], datasetRevision: 17, asOf: null });
    },
  });

  await client.rating({
    platform: "vk",
    period: "7d",
    channelSort: "views",
    channelDirection: "asc",
    postSort: "shares",
    postDirection: "desc",
    entityLimit: 500,
  });

  const url = new URL(seenUrl);
  assert.equal(url.pathname, "/api/v1/rating");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    platform: "vk",
    period: "7d",
    channel_sort: "views",
    channel_direction: "asc",
    post_sort: "shares",
    post_direction: "desc",
    entityLimit: "200",
  });
});
