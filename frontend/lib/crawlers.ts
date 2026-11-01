/**
 * Роботы, собирающие тексты для обучения и поиска ИИ. В сентябре 2026 GPTBot
 * за сутки обошёл десятки тысяч страниц публикаций, и каждая строилась заново
 * из холодной истории замеров — сервер стоял загруженным полностью. nginx (operations/nginx/m-ranked.conf)
 * отвечает им 403 на всё, кроме этого файла; здесь им сказано то же самое.
 */
export const AI_CRAWLERS = [
  "GPTBot", "OAI-SearchBot", "ClaudeBot", "Claude-SearchBot", "anthropic-ai", "CCBot", "Amazonbot",
  "Bytespider", "meta-externalagent", "meta-webindexer", "FacebookBot", "PerplexityBot", "Google-Extended", "Applebot-Extended",
  "cohere-ai", "cohere-training-data-crawler", "Diffbot", "ImagesiftBot", "Omgilibot", "YouBot", "Timpibot",
  "AI2Bot", "PanguBot", "Kangaroo Bot", "Sidetrade indexer bot", "img2dataset", "webzio-extended",
] as const;

/**
 * SEO-сервисы. Это не поисковики: на выдачу Яндекса и Google не влияют, а
 * обходят все страницы постов — за 15 дней до 18.10.2026 это 41% всего времени
 * рендера промахов. Их база — готовый список наших страниц для чужих
 * обходчиков: 18.10 по нему через тысячи домашних прокси выкачали 13,8 тыс.
 * постов. nginx отвечает им 403 на всё, кроме этого файла (класс seo).
 */
export const SEO_CRAWLERS = [
  "SemrushBot", "SiteAuditBot", "SplitSignalBot", "AhrefsBot", "AhrefsSiteAudit", "MJ12bot",
  "SERankingBacklinksBot", "SERankingBot", "DotBot", "BLEXBot", "DataForSeoBot", "serpstatbot", "Barkrowler",
  "MegaIndex.ru", "Screaming Frog SEO Spider", "ZoominfoBot",
] as const;
