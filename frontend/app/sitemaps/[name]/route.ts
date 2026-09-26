import { api, ApiError } from "@/lib/api";
import { publicOrigin } from "@/lib/deployment";
import { pageEntries, publicationEntries, urlset, xmlResponse } from "@/lib/sitemap";

export const dynamic = "force-dynamic";

/** /sitemaps/pages.xml и /sitemaps/publications-N.xml. */
export async function GET(_request: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  const publications = /^publications-(\d{1,4})\.xml$/.exec(name);
  if (name !== "pages.xml" && !publications) return new Response("Not found\n", { status: 404 });
  try {
    if (name === "pages.xml") return xmlResponse(urlset(publicOrigin(), pageEntries(await api.sitemapSummary())));
    const page = await api.sitemapPublications(Number(publications![1]));
    return xmlResponse(urlset(publicOrigin(), publicationEntries(page.items)));
  } catch (error) {
    if (error instanceof ApiError && error.status === 400) return new Response("Not found\n", { status: 404 });
    return new Response("Карта сайта временно недоступна\n", { status: 503, headers: { "Retry-After": "600", "Cache-Control": "no-store" } });
  }
}
