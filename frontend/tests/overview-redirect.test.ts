import assert from "node:assert/strict";
import test from "node:test";
import { overviewRedirect } from "../lib/overview-redirect";

test("старые ссылки обзора ведут на /rating с теми же параметрами", () => {
  assert.equal(overviewRedirect(new URL("https://site.test/?platform=vk&period=7d"))?.href, "https://site.test/rating?platform=vk&period=7d");
  assert.equal(overviewRedirect(new URL("https://site.test/?q=%D0%9C%D0%93%D0%A3"))?.pathname, "/rating");
  assert.equal(overviewRedirect(new URL("https://site.test/")), null);
  assert.equal(overviewRedirect(new URL("https://site.test/?utm_source=tg")), null);
  assert.equal(overviewRedirect(new URL("https://site.test/statistics?platform=vk")), null);
});
