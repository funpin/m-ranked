const routes = {
  channels: { resource: "accounts", legacyType: "channels", message: "Канал не найден", html: true },
  posts: { resource: "publications", legacyType: "posts", message: "Публикация не найдена", html: true },
  "platform-accounts": { resource: "accounts", legacyType: "platform_accounts", message: "Аккаунт не найден", html: false },
  "platform-posts": { resource: "publications", legacyType: "platform_posts", message: "Публикация не найдена", html: false },
  institutions: { resource: "institutions", legacyType: null, message: "Вуз не найден", html: false },
} as const;

export async function legacyDetailError(url: URL, apiOrigin: string,
  fetcher: typeof fetch = fetch): Promise<Response | null> {
  const match = /^\/(channels|posts|platform-accounts|platform-posts|institutions)\/(\d+)$/.exec(url.pathname);
  if (!match) return null;
  if ((match[1] === "channels" || match[1] === "posts") && url.searchParams.has("platform")) return null;
  const route = routes[match[1] as keyof typeof routes];
  const target = new URL(`/api/v1/${route.resource}/${match[2]}`, apiOrigin);
  if (route.legacyType) target.searchParams.set("legacyType", route.legacyType);
  let response: Response;
  try { response = await fetcher(target, { cache: "no-store", signal: AbortSignal.timeout(5000) }); }
  catch { return null; } // The page's existing unavailable state owns dependency failures.
  const status = response.status;
  await response.body?.cancel();
  if (status !== 404) return null;
  if (!route.html) return Response.json({ detail: route.message }, { status: 404, headers: { "Cache-Control": "no-store" } });
  // Unstyled semantic HTML preserves legacy pixels while supplying document
  // language, title and landmark for assistive technology.
  return new Response(`<!doctype html><html lang="ru"><head><title>${route.message}</title></head><body><main>${route.message}</main></body></html>`,
    { status: 404, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}
