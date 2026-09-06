import assert from "node:assert/strict";
import test from "node:test";
import { legacyDetailError } from "../lib/legacy-detail-error";

test("legacy missing detail retains status/text and semantic HTML without styles", async () => {
  const response = await legacyDetailError(new URL("https://site.test/channels/999"), "https://api.test", async (input) => {
    assert.equal(String(input),"https://api.test/api/v1/accounts/999?legacyType=channels");
    return new Response("missing",{status:404});
  });
  assert.equal(response?.status,404);
  assert.match(await response!.text(),/<html lang="ru">.*<main>Канал не найден<\/main>/);
});

test("generic missing detail preserves legacy JSON and unavailable API stays with page", async () => {
  const url = new URL("https://site.test/platform-posts/999");
  const response = await legacyDetailError(url,"https://api.test",async () => new Response(null,{status:404}));
  assert.deepEqual(await response!.json(),{detail:"Публикация не найдена"});
  assert.equal(await legacyDetailError(url,"https://api.test",async () => new Response(null,{status:503})),null);
  assert.equal(await legacyDetailError(new URL("https://site.test/rating"),"https://api.test",async () => {throw Error("must not fetch");}),null);
});

test("old namespaces with the same number redirect to distinct UUIDs and retain query values", async () => {
  const telegram = "00000001-0000-4000-8000-000000000001";
  const vk = "00000002-0000-4000-8000-000000000001";
  for (const [route, id, platform] of [["channels", telegram, "telegram"], ["platform-accounts", vk, "vk"]]) {
    const result = await legacyDetailError(new URL(`https://site.test/${route}/1?period=7d&x=a&x=b`), "https://api.test",
      async () => Response.json({ accountId: id, platform }));
    assert.equal(result?.status, 308);
    assert.equal(result?.headers.get("Location"), `https://site.test/accounts/${id}?period=7d&x=a&x=b`);
  }
  const result = await legacyDetailError(new URL("https://site.test/posts/1?history_limit=500"), "https://api.test",
    async () => Response.json({ publicationId: telegram, platform: "telegram" }));
  assert.equal(result?.headers.get("Location"), `https://site.test/publications/${telegram}?history_limit=500`);
});
