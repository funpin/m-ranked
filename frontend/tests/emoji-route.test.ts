import assert from "node:assert/strict";
import test from "node:test";
import { GET } from "../app/emoji/[[...emojiPath]]/route";
import { createEmojiRoute } from "../lib/emoji-route";

test("emoji facade preserves bytes, MIME, cache header, and target URL", async () => {
  const requests: Array<{ url: string; init: RequestInit | undefined }> = [];
  const route = createEmojiRoute({
    baseUrl: "https://api.example.test/root/",
    fetcher: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(new Uint8Array([0, 1, 2, 255]), {
        headers: { "Content-Type": "image/png; charset=binary", "Content-Length": "4" },
      });
    },
  });

  const response = await route("12345678901234567890123456789012");

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "image/png");
  assert.equal(response.headers.get("cache-control"), "public, max-age=21600");
  assert.equal(response.headers.get("content-length"), "4");
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()), new Uint8Array([0, 1, 2, 255]));
  assert.equal(
    requests[0]?.url,
    "https://api.example.test/api/v1/emoji/12345678901234567890123456789012",
  );
  assert.equal(requests[0]?.init?.method, "GET");
  assert.equal(requests[0]?.init?.cache, "no-store");
  assert.equal(requests[0]?.init?.redirect, "error");
});

test("emoji facade rejects invalid IDs without contacting Spring", async () => {
  let requests = 0;
  const route = createEmojiRoute({
    fetcher: async () => {
      requests += 1;
      return new Response();
    },
  });

  for (const identifier of ["", "abc", "+42", "١٢", "123456789012345678901234567890123"]) {
    const response = await route(identifier);
    assert.equal(response.status, 404);
    assert.equal(response.headers.get("content-type"), "application/json");
    assert.equal(response.headers.get("content-length"), "47");
    assert.equal(response.headers.get("cache-control"), null);
    assert.deepEqual(await response.json(), { detail: "Реакция не найдена" });
  }
  assert.equal(requests, 0);
});

test("emoji facade maps Spring 404 to the exact legacy response", async () => {
  const route = createEmojiRoute({
    fetcher: async () => Response.json(
      { type: "urn:m-ranked:problem:not-found", status: 404 },
      { status: 404 },
    ),
  });

  const response = await route("42");

  assert.equal(response.status, 404);
  assert.equal(response.headers.get("content-type"), "application/json");
  assert.equal(response.headers.get("content-length"), "47");
  assert.equal(response.headers.get("cache-control"), null);
  assert.equal(await response.text(), '{"detail":"Реакция не найдена"}');
});

test("emoji catch-all preserves framework 404 for missing, slash, and encoded-slash paths", async () => {
  for (const emojiPath of [undefined, ["12", "34"], ["12/34"]]) {
    const response = await GET(
      new Request("https://m-ranked.example/emoji/12%2F34"),
      { params: Promise.resolve({ emojiPath }) },
    );
    assert.equal(response.status, 404);
    assert.equal(response.headers.get("content-type"), "application/json");
    assert.equal(response.headers.get("content-length"), "22");
    assert.equal(response.headers.get("cache-control"), null);
    assert.equal(await response.text(), '{"detail":"Not Found"}');
  }
});

test("emoji facade fails closed on upstream errors and normalizes unknown MIME", async () => {
  const unavailable = createEmojiRoute({
    fetcher: async () => {
      throw new Error("connection failed");
    },
  });
  const failed = await unavailable("42");
  assert.equal(failed.status, 500);
  assert.equal(failed.headers.get("cache-control"), null);
  assert.equal(failed.headers.get("content-length"), "21");
  assert.equal(await failed.text(), "Internal Server Error");

  const unknownMime = createEmojiRoute({
    fetcher: async () => new Response(new Uint8Array([1]), {
      headers: { "Content-Type": "application/octet-stream" },
    }),
  });
  const fallback = await unknownMime("42");
  assert.equal(fallback.status, 200);
  assert.equal(fallback.headers.get("content-type"), "image/webp");

  const oversized = createEmojiRoute({
    fetcher: async () => new Response(new Uint8Array([1]), {
      headers: { "Content-Type": "image/png", "Content-Length": "2000001" },
    }),
  });
  assert.equal((await oversized("42")).status, 500);
});
