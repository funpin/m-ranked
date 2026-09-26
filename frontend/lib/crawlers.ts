/**
 * Роботы, собирающие тексты для обучения и поиска ИИ. В сентябре 2026 GPTBot
 * за сутки обошёл десятки тысяч страниц публикаций, и каждая строилась заново
 * из холодной истории замеров — сервер стоял загруженным полностью. nginx (operations/nginx/m-ranked.conf)
 * отвечает им 403 на всё, кроме этого файла; здесь им сказано то же самое.
 */
export const AI_CRAWLERS = [
  "GPTBot", "OAI-SearchBot", "ClaudeBot", "Claude-SearchBot", "anthropic-ai", "CCBot", "Amazonbot",
  "Bytespider", "meta-externalagent", "FacebookBot", "PerplexityBot", "Google-Extended", "Applebot-Extended",
  "cohere-ai", "cohere-training-data-crawler", "Diffbot", "ImagesiftBot", "Omgilibot", "YouBot", "Timpibot",
  "AI2Bot", "PanguBot", "Kangaroo Bot", "Sidetrade indexer bot", "img2dataset", "webzio-extended",
] as const;
