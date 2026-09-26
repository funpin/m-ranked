import { api } from "@/lib/api";
import { publicOrigin } from "@/lib/deployment";
import { sitemapIndex, xmlResponse } from "@/lib/sitemap";

export const dynamic = "force-dynamic";

/** Индекс карты сайта: страницы разделов, аккаунтов и вузов плюс файлы постов. */
export async function GET() {
  try {
    const summary = await api.sitemapSummary();
    return xmlResponse(sitemapIndex(publicOrigin(), summary.publicationPages));
  } catch {
    return new Response("Карта сайта временно недоступна\n", { status: 503, headers: { "Retry-After": "600", "Cache-Control": "no-store" } });
  }
}
