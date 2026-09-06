export interface PublicRepresentation {
  body: string;
  headers: [string, string][];
  status: number;
}

export interface PublicResponseCache {
  load(key: string[], tags: string[], produce: () => Promise<PublicRepresentation>): Promise<PublicRepresentation>;
}

const PUBLIC_DOMAINS = /^\/api\/v1\/(overview|rating|compare(?:\/candidates)?|institutions\/\d+(?:\/accounts)?|accounts\/\d+(?:\/publications)?|publications\/\d+(?:\/history)?)$/;

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

class RevisionRace extends Error {}

export async function revisionCachedResponse(url: URL, cache: PublicResponseCache,
  fetchResponse: (url: URL) => Promise<Response>, readRevision: () => Promise<number | {datasetRevision:number;representationVersion:string}>): Promise<Response> {
  if (!PUBLIC_DOMAINS.test(url.pathname)) return fetchResponse(url);
  for (let attempt = 0; attempt < 3; attempt++) {
    // Read PG's published revision on every request. A lost invalidation event cannot select a stale entry.
    const state = await readRevision();
    const revision = typeof state === "number" ? state : state.datasetRevision;
    const identity = publicCacheKey(url, revision,typeof state === "number" ? undefined : state.representationVersion)!;
    try {
      const cached = await cache.load(identity.key, identity.tags, async () => {
        const response = await fetchResponse(url);
        if (!response.ok) throw response;
        const body = await response.text();
        const data = JSON.parse(body) as { datasetRevision: number };
        if (data.datasetRevision !== revision) throw new RevisionRace();
        return { body, headers: [...response.headers], status: response.status };
      });
      // Validate even if a custom/failed L1 returns the wrong representation.
      if ((JSON.parse(cached.body) as { datasetRevision: number }).datasetRevision !== revision) throw new RevisionRace();
      return new Response(cached.body, { status: cached.status, headers: cached.headers });
    } catch (error) {
      if (error instanceof Response) return error;
      if (!(error instanceof RevisionRace)) throw error;
    }
  }
  throw new Error("Dataset changed repeatedly while reading a public representation");
}
