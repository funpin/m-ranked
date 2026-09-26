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
  assert.deepEqual(second, first);
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

test("account publication query forwards the selected Moscow day", async () => {
  let seenUrl = "";
  const client = createApiClient({
    baseUrl: "https://api.example.test",
    fetcher: async (input) => {
      seenUrl = String(input);
      return Response.json({ items: [], nextCursor: null, datasetRevision: 17, asOf: "2026-09-18T12:00:00Z" });
    },
  });

  await client.accountPublications(12, "channels", 100, undefined, 17, "2026-09-18");
  const query = new URL(seenUrl).searchParams;
  assert.equal(query.get("day"), "2026-09-18");
  assert.equal(query.get("revision"), "17");
});

test("analysis client uses its independent endpoint and keeps an unanalyzed post a 200 body", async () => {
  let seenUrl="";
  const client=createApiClient({baseUrl:"https://api.example.test",fetcher:async(input)=>{
    seenUrl=String(input);return Response.json({publicationId:"10000000-0000-4000-8000-000000000001",
      datasetRevision:17,status:"pending",level:null,levelLabel:"ещё не проанализирован",levelSymbol:"·",
      signals:[],quality:null,analyzedAt:null,lagSeconds:null,normVersion:null,detectorVersions:{},
      reviewStatus:"unreviewed",methodologyVersion:"anomaly-dynamics-v2",disclaimer:"informational"},{headers:{ETag:'"analysis-2"'}});
  }});
  const value=await client.publicationAnomalyAnalysis("10000000-0000-4000-8000-000000000001");
  assert.equal(value.level,null);
  assert.match(seenUrl,/\/api\/v1\/publications\/10000000-0000-4000-8000-000000000001\/anomaly-analysis$/);
});

test("statistics client sends every result dimension and bounds the limit", async () => {
  let seenUrl = "";
  const client = createApiClient({
    baseUrl: "https://api.example.test",
    fetcher: async (input) => {
      seenUrl = String(input);
      return Response.json({ sections: [], entities: [], datasetRevision: 17, asOf: "2026-01-01T00:00:00Z" });
    },
  });

  await client.statistics({
    view: "entities",
    platform: "vk",
    period: "7d",
    q: "  @alpha  ",
    publicationSort: "interactions",
    publicationDirection: "asc",
    entitySort: "views",
    entityDirection: "desc",
    limit: 500,
  });

  const url = new URL(seenUrl);
  assert.equal(url.pathname, "/api/v1/statistics");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    view: "entities",
    platform: "vk",
    period: "7d",
    q: "@alpha",
    publication_sort: "interactions",
    publication_direction: "asc",
    entity_sort: "views",
    entity_direction: "desc",
    limit: "50",
  });
});
