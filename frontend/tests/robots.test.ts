import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import robots from "../app/robots";
import { AI_SEARCH_CRAWLERS, AI_TRAINING_CRAWLERS, SEO_CRAWLERS } from "../lib/crawlers";

test("robots.txt закрывает сайт для ИИ-роботов и оставляет его поисковикам", () => {
  const rules = [robots().rules].flat();
  const ai = rules.find((rule) => [rule.userAgent].flat().includes("GPTBot"));
  assert.equal(ai?.disallow, "/");
  const everyone = rules.find((rule) => rule.userAgent === "*");
  assert.equal(everyone?.allow, "/");
  assert.ok([everyone?.disallow].flat().includes("/manage"));
  assert.ok([everyone?.disallow].flat().includes("/*?*history_limit="));
});

function agentClassPatterns(klass: string): string[] {
  const config = readFileSync(new URL("../../operations/nginx/traffic.conf", import.meta.url), "utf8");
  const map = /map \$http_user_agent \$m_ranked_agent_class \{([^}]*)\}/.exec(config);
  assert.ok(map, "в traffic.conf нет карты классов клиентов");
  return [...map[1]!.matchAll(new RegExp(`"~\\*\\(([^)]*)\\)" ${klass};`, "g"))]
    .flatMap((item) => item[1]!.split("|")).map((item) => item.toLowerCase());
}

test("nginx относит ИИ-роботов из robots.txt к тем же классам", () => {
  const training = agentClassPatterns("ai_training");
  for (const agent of AI_TRAINING_CRAWLERS) {
    assert.ok(training.some((pattern) => agent.toLowerCase().includes(pattern)), `${agent} не ai_training в nginx`);
  }
  const search = agentClassPatterns("ai_search");
  for (const agent of AI_SEARCH_CRAWLERS) {
    assert.ok(search.some((pattern) => agent.toLowerCase().includes(pattern)), `${agent} не ai_search в nginx`);
  }
});

test("поисковые ИИ-роботы открыты: без своей группы в robots.txt и без 403 в nginx", () => {
  const rules = [robots().rules].flat();
  for (const agent of AI_SEARCH_CRAWLERS) {
    assert.ok(!rules.some((rule) => [rule.userAgent].flat().includes(agent)), `${agent} получил свою группу`);
  }
  const policy = readFileSync(new URL("../../operations/nginx/crawler-policy.conf", import.meta.url), "utf8");
  assert.doesNotMatch(policy, /^\s*ai_search 1;$/m);
  assert.match(policy, /^\s*ai_training 1;$/m);
});

test("robots.txt и nginx закрывают сайт для SEO-сервисов", () => {
  const rules = [robots().rules].flat();
  const seo = rules.find((rule) => [rule.userAgent].flat().includes("SemrushBot"));
  assert.equal(seo?.disallow, "/");
  const config = readFileSync(new URL("../../operations/nginx/traffic.conf", import.meta.url), "utf8");
  const map = /map \$http_user_agent \$m_ranked_agent_class \{([^}]*)\}/.exec(config);
  assert.ok(map, "в traffic.conf нет карты классов клиентов");
  const patterns = [...map[1]!.matchAll(/"~\*\(([^)]*)\)" seo;/g)]
    .flatMap((item) => item[1]!.split("|")).map((item) => item.toLowerCase());
  for (const agent of SEO_CRAWLERS) {
    assert.ok(patterns.some((pattern) => agent.toLowerCase().includes(pattern)), `${agent} не распознаётся в nginx`);
  }
  const policy = readFileSync(new URL("../../operations/nginx/crawler-policy.conf", import.meta.url), "utf8");
  assert.match(policy, /^\s*seo 1;$/m);
});
