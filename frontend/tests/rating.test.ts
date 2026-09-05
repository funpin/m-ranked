import assert from "node:assert/strict";
import test from "node:test";
import { normalizeRatingPeriod, normalizeRatingQuery } from "../lib/rating";

test("rating distinguishes the omitted 30d default from the invalid 1d fallback", () => {
  assert.equal(normalizeRatingPeriod(undefined), "30d");
  assert.equal(normalizeRatingPeriod("7d"), "7d");
  assert.equal(normalizeRatingPeriod("not-a-period"), "1d");
});

test("rating uses Telegram-specific sort fallbacks and preserves directions", () => {
  assert.deepEqual(normalizeRatingQuery({ platform: "telegram" }), {
      platform: "telegram",
      period: "30d",
      channelSort: "engagement",
      postSort: "view_share",
      channelDirection: "desc",
      postDirection: "desc",
  });
  assert.deepEqual(normalizeRatingQuery({
      platform: "telegram",
      channel_sort: "views",
      post_sort: "shares",
      channel_direction: "asc",
      post_direction: "asc",
  }), {
      platform: "telegram",
      period: "30d",
      channelSort: "engagement",
      postSort: "reactions",
      channelDirection: "asc",
      postDirection: "asc",
  });
});

test("rating keeps VK shares but applies the RUTUBE post fallback", () => {
  assert.equal(normalizeRatingQuery({ platform: "vk", post_sort: "shares" }).postSort, "shares");
  assert.equal(normalizeRatingQuery({ platform: "rutube", post_sort: "shares" }).postSort, "view_share");
});

test("rating retains MAX/all for the page's explicit pending branch", () => {
  assert.equal(normalizeRatingQuery({ platform: "max" }).platform, "max");
  assert.equal(normalizeRatingQuery({ platform: "all" }).platform, "all");
});
