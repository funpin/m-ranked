export interface PublicRepresentation {
  body: string;
  headers: [string, string][];
  status: number;
}

export interface PublicResponseCache {
  load(key: string[], tags: string[], produce: () => Promise<PublicRepresentation>): Promise<PublicRepresentation>;
}

const PUBLIC_DOMAINS = /^\/api\/v1\/(overview|rating|compare(?:\/candidates)?|institutions\/\d+(?:\/accounts)?|accounts\/\d+(?:\/publications)?|publications\/\d+(?:\/history)?)$/;

/**
 * Как долго один и тот же снимок обслуживает читателей.
 *
 * Ревизия набора данных на проде меняется раз в 1.9 секунды: её двигает каждая
 * запись коллектора. Ключ кэша включал её, поэтому обновлялся быстрее, чем
 * приходил второй читатель, — и каждый просмотр страницы заново спрашивал у
 * API и ревизию, и сами данные. На экране показаны приросты за три часа,
 * сутки, неделю и месяц; отставание в несколько секунд в них не видно, а
 * какой это снимок, видно по asOf и datasetRevision в самом ответе.
 */
export const FRESHNESS_MS = 10_000;

export interface AuthoritativeState { datasetRevision: number; representationVersion: string }

export function publicCacheKey(url: URL, revision: number, representationVersion="unversioned"): { key: string[]; tags: string[] } | null {
  const domain = PUBLIC_DOMAINS.exec(url.pathname)?.[1]?.split("/")[0];
  if (!domain) return null;
  const canonical = new URL(url);
  // Stable sort retains the intentional order of repeated selection IDs.
  canonical.searchParams.sort();
  const platform = canonical.searchParams.get("platform") ?? "identity";
  return { key: ["m-ranked-public-v1", url.origin, domain, canonical.pathname, canonical.search, String(revision),representationVersion],
    tags: [`m-ranked:${domain}`, `m-ranked:${domain}:${platform}`, `m-ranked:revision:${revision}`] };
}

/** Просит ли вызывающий конкретный снимок данных вместо текущего. */
function isPinned(url: URL) {
  const value = Number(url.searchParams.get("revision"));
  return Number.isInteger(value) && value > 0;
}

/**
 * Сколько живёт запомненный ответ о текущем снимке.
 *
 * Читать его на каждый запрос было двойной тратой: лишний заход по сети и в
 * базу, и ключ, который заведомо не повторится. Ответ запоминается на окно
 * свежести — за окно набегает одно чтение на процесс, а не одно на каждый
 * вызов API.
 */
let remembered: { state: AuthoritativeState; until: number } | null = null;
let pending: Promise<AuthoritativeState> | null = null;

/** Забывает запомненный снимок. Только для тестов. */
export function forgetAuthoritativeState() {
  remembered = null;
  pending = null;
}

async function authoritativeState(read: () => Promise<number | AuthoritativeState>): Promise<AuthoritativeState> {
  const now = Date.now();
  if (remembered && remembered.until > now) return remembered.state;
  // Параллельные запросы одной страницы ждут одно чтение, а не каждый своё.
  pending ??= (async () => {
    const value = await read();
    const state = typeof value === "number"
      ? { datasetRevision: value, representationVersion: "unversioned" }
      : value;
    remembered = { state, until: Date.now() + FRESHNESS_MS };
    return state;
  })().finally(() => { pending = null; });
  return pending;
}

export async function revisionCachedResponse(url: URL, cache: PublicResponseCache,
  fetchResponse: (url: URL) => Promise<Response>, readRevision: () => Promise<number | AuthoritativeState>): Promise<Response> {
  if (!PUBLIC_DOMAINS.test(url.pathname)) return fetchResponse(url);
  // Запрос с явно закреплённой ревизией мимо кэша: вызывающий сам назвал
  // снимок, который ему нужен, чтобы собрать страницу из одного среза.
  if (isPinned(url)) return fetchResponse(url);
  const state = await authoritativeState(readRevision);
  const identity = publicCacheKey(url, state.datasetRevision, state.representationVersion)!;
  try {
    const cached = await cache.load(identity.key, identity.tags, async () => {
      const response = await fetchResponse(url);
      if (!response.ok) throw response;
      return { body: await response.text(), headers: [...response.headers], status: response.status };
    });
    return new Response(cached.body, { status: cached.status, headers: cached.headers });
  } catch (error) {
    if (error instanceof Response) return error;
    throw error;
  }
}
