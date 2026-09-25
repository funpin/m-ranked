import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import robots from "../app/robots";
import { AI_CRAWLERS } from "../lib/crawlers";

test("robots.txt закрывает сайт для ИИ-роботов и оставляет его поисковикам", () => {
  const rules = [robots().rules].flat();
  const ai = rules.find((rule) => [rule.userAgent].flat().includes("GPTBot"));
  assert.equal(ai?.disallow, "/");
  const everyone = rules.find((rule) => rule.userAgent === "*");
  assert.equal(everyone?.allow, "/");
  assert.ok([everyone?.disallow].flat().includes("/manage"));
  assert.ok([everyone?.disallow].flat().includes("/*?*history_limit="));
});

test("nginx узнаёт тех же ИИ-роботов, что перечислены в robots.txt", () => {
  const config = readFileSync(new URL("../../operations/nginx/traffic.conf", import.meta.url), "utf8");
  const map = /map \$http_user_agent \$m_ranked_agent_class \{([^}]*)\}/.exec(config);
  assert.ok(map, "в traffic.conf нет карты классов клиентов");
  // Все шаблоны ИИ-классов карты: запросы по просьбе человека, поиск, обучение.
  const patterns = [...map[1]!.matchAll(/"~\*\(([^)]*)\)" (ai_\w+);/g)]
    .flatMap((item) => item[1]!.split("|")).map((item) => item.toLowerCase());
  for (const agent of AI_CRAWLERS) {
    assert.ok(patterns.some((pattern) => agent.toLowerCase().includes(pattern)), `${agent} не распознаётся в nginx`);
  }
});
