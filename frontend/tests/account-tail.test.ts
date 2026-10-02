import assert from "node:assert/strict";
import test from "node:test";
import { tailSummary } from "../lib/account-tail";
import type { AccountTailProfile } from "../lib/types";

const totals = { posts: 10, earlyViews: 10000, earlyReactions: 300, lateViews: 2000, lateReactions: 120,
  earlyRate: 0.03, lateRate: 0.06, ratio: 2 };

function profile(overrides: Partial<AccountTailProfile> = {}): AccountTailProfile {
  return {
    accountId: "10000000-0000-4000-8000-000000000001", datasetRevision: 1, status: "computed",
    computedFor: "2026-09-29", computedAt: "2026-09-29T02:00:00Z", platform: "max", level: 2,
    levelLabel: "устойчиво необычный", abstainReason: null,
    metrics: {
      methodVersion: "account-tail-v1", windowStart: "2026-09-08", windowEnd: "2026-09-28", ...totals,
      halves: { earlier: totals, recent: totals },
      days: [{ day: "2026-09-27", observed: 10, active: 6, reactions: 9 }, { day: "2026-09-28", observed: 0, active: 0, reactions: 0 }],
      activeDays: 5, activeWeeks: 2, wideDays: 1, breadth: null, roundedPosts: 0,
      cohort: { accounts: 80, median: 0.18, p90: 0.79, threshold: 0.79, rank: 0.99 },
    },
    history: [], methodologyVersion: "account-tail-v1", disclaimer: "", ...overrides,
  };
}

test("the profile states numbers against the platform without claims about intent", () => {
  const view = tailSummary(profile());
  assert.equal(view.label, "устойчиво необычный");
  assert.equal(view.earlyRate, "3,0");
  assert.equal(view.ratio, "2,00×");
  assert.match(view.sentence!, /у типичного аккаунта площадки — 0,18×/);
  assert.match(view.sentence!, /в 5 сутках из 2\./);
  assert.match(view.cohortText!, /99 %/);
  assert.doesNotMatch(view.sentence!, /накрут|мошен|доказ/);
});

test("pending and abstaining profiles keep their reason instead of looking ordinary", () => {
  const pending = tailSummary(profile({ status: "pending", metrics: null, level: null, levelLabel: "ещё не проанализирован" }));
  assert.equal(pending.metrics, null);
  assert.equal(pending.label, "ещё не рассчитан");
  const abstained = profile({ level: null, levelLabel: "недостаточно данных", abstainReason: "small_cohort" });
  abstained.metrics = { ...abstained.metrics!, abstainText: "мало аккаунтов площадки", cohort: null, ratio: null };
  const view = tailSummary(abstained);
  assert.equal(view.label, "недостаточно данных");
  assert.equal(view.abstainText, "мало аккаунтов площадки");
  assert.equal(view.ratio, "—");
});
