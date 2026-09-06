import { accountHref, publicationHref, UUID_PATTERN } from "./entity-routes";
import { legacyPlatformDecision } from "./params";
const routes = {
  accounts: { resource: "accounts", legacyType: null, message: "Аккаунт не найден", html: true },
  publications: { resource: "publications", legacyType: null, message: "Публикация не найдена", html: true },
  channels: { resource: "accounts", legacyType: "channels", message: "Канал не найден", html: true },
  posts: { resource: "publications", legacyType: "posts", message: "Публикация не найдена", html: true },
  "platform-accounts": { resource: "accounts", legacyType: "platform_accounts", message: "Аккаунт не найден", html: false },
  "platform-posts": { resource: "publications", legacyType: "platform_posts", message: "Публикация не найдена", html: false },
  institutions: { resource: "institutions", legacyType: null, message: "Вуз не найден", html: false },
} as const;

export async function legacyDetailError(url: URL, apiOrigin: string,
  fetcher: typeof fetch = fetch): Promise<Response | null> {
  const match = /^\/(channels|posts|platform-accounts|platform-posts|institutions)\/(\d+)$/.exec(url.pathname)
    ?? /^\/(accounts|publications)\/([0-9a-f-]{36})$/i.exec(url.pathname);
  if (!match) return null;
  const route = routes[match[1] as keyof typeof routes];
  const target = new URL(`/api/v1/${route.resource}/${match[2]}`, apiOrigin);
  if (route.legacyType) target.searchParams.set("legacyType", route.legacyType);
  let response: Response;
  try { response = await fetcher(target, { cache: "no-store", signal: AbortSignal.timeout(5000) }); }
  catch { return null; } // The page's existing unavailable state owns dependency failures.
  const status = response.status;
  if (response.ok && route.legacyType) {
    const entity = await response.json() as { accountId?: string; publicationId?: string; platform: "telegram" | "vk" | "max" | "rutube" };
    const generic = match[1].startsWith("platform-");
    if (legacyPlatformDecision(url.searchParams.getAll("platform"), entity.platform, generic) === "not_found") return null;
    const id = route.resource === "accounts" ? entity.accountId : entity.publicationId;
    if (!id || !UUID_PATTERN.test(id)) return null;
    const destination = new URL(url);
    destination.pathname = route.resource === "accounts" ? accountHref(id) : publicationHref(id);
    return new Response(null, { status: 308, headers: { Location: destination.href, "Cache-Control": "no-store" } });
  }
  await response.body?.cancel();
  if (status !== 404) return null;
  if (!route.html) return Response.json({ detail: route.message }, { status: 404, headers: { "Cache-Control": "no-store" } });
  // Unstyled semantic HTML preserves legacy pixels while supplying document
  // language, title and landmark for assistive technology.
  return new Response(`<!doctype html><html lang="ru"><head><title>${route.message}</title></head><body><main>${route.message}</main></body></html>`,
    { status: 404, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}
