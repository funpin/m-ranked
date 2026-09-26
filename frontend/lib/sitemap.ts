import { accountHref, publicationHref } from "./entity-routes";
import { ARTICLES } from "./methodology";

/** Карта сайта собирается из API и живёт в кэше nginx шесть часов: адреса и
 *  lastmod меняются медленно, а файл постов — это 20 тысяч строк. */
export const SITEMAP_CACHE_SECONDS = 6 * 3600;

const STATIC_PATHS = [
  "/", "/rating", "/statistics", "/compare", "/methodology",
  ...ARTICLES.map((article) => `/methodology/${article.slug}`), "/methodology/api",
] as const;

function escape(value: string) {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function lastmod(value: string | null | undefined) {
  if (!value) return "";
  const time = Date.parse(value);
  return Number.isFinite(time) ? `<lastmod>${new Date(time).toISOString()}</lastmod>` : "";
}

export function urlset(origin: URL, entries: { path: string; lastModified?: string | null }[]) {
  const body = entries.map(({ path, lastModified }) =>
    `<url><loc>${escape(new URL(path, origin).href)}</loc>${lastmod(lastModified)}</url>`).join("");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${body}</urlset>\n`;
}

export function sitemapIndex(origin: URL, publicationPages: number) {
  const files = ["pages.xml", ...Array.from({ length: publicationPages }, (_, page) => `publications-${page}.xml`)];
  const body = files.map((file) => `<sitemap><loc>${escape(new URL(`/sitemaps/${file}`, origin).href)}</loc></sitemap>`).join("");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${body}</sitemapindex>\n`;
}

export function pageEntries(summary: { accounts: { accountId: string; lastModified?: string | null }[]; institutions: { legacyId: number }[] }) {
  return [
    ...STATIC_PATHS.map((path) => ({ path })),
    ...summary.institutions.map(({ legacyId }) => ({ path: `/institutions/${legacyId}` })),
    ...summary.accounts.map(({ accountId, lastModified }) => ({ path: accountHref(accountId), lastModified })),
  ];
}

export function publicationEntries(items: { publicationId: string; lastModified: string }[]) {
  return items.map(({ publicationId, lastModified }) => ({ path: publicationHref(publicationId), lastModified }));
}

export function xmlResponse(body: string) {
  return new Response(body, {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": `public, max-age=${SITEMAP_CACHE_SECONDS}`,
      // Срок в кэше nginx; до клиента не доходит.
      "X-Accel-Expires": String(SITEMAP_CACHE_SECONDS),
    },
  });
}
