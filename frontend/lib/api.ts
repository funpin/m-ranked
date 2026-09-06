import createClient from "openapi-fetch";
import type { paths } from "../../contracts/openapi/m-ranked-v1-client";
import { MAX_COMPARISON_INSTITUTIONS, COMPARISON_PAGE_SIZE } from "./types";
import type { ActivityRatingRequest, ApiProblem, ComparisonRequest, LegacyAccountType, LegacyPublicationType, Period, Platform, SortDirection } from "./types";
import type { OverviewSort } from "./params";
import { revisionCachedResponse, type PublicResponseCache } from "./revision-cache";

type Fetcher = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
interface CacheEntry { etag: string; body: string; headers: [string, string][] }

export class ApiError extends Error {
  constructor(readonly status: number, message: string, readonly problem: ApiProblem | null = null) {
    super(message); this.name = "ApiError";
  }
}

export interface ApiClientOptions {
  baseUrl?: string;
  fetcher?: Fetcher;
  timeoutMs?: number;
  cacheEntries?: number;
  publicCache?: PublicResponseCache;
}

export function createApiClient(options: ApiClientOptions = {}) {
  const base = new URL(options.baseUrl ?? process.env.API_BASE_URL ?? "http://127.0.0.1:8080");
  if (!["https:", "http:"].includes(base.protocol) || base.username || base.password) throw new Error("API_BASE_URL must be an HTTP(S) origin without credentials");
  const fetcher: Fetcher = options.fetcher ?? ((input, init) => fetch(input, init));
  const timeoutMs = options.timeoutMs ?? 8_000;
  const limit = Math.max(0, options.cacheEntries ?? 128);
  const cache = new Map<string, CacheEntry>();

  async function revalidate(url: URL): Promise<Response> {
    const key = url.toString();
    const cached = cache.get(key);
    const headers = new Headers({ Accept: "application/json" });
    if (cached) headers.set("If-None-Match", cached.etag);
    let response: Response;
    try {
      response = await fetcher(url, { method: "GET", headers, cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
    } catch { throw new ApiError(0, "Spring API is unavailable"); }
    if (response.status === 304) {
      if (!cached) throw new ApiError(502, "API returned 304 without a cached representation");
      return new Response(cached.body, { headers: cached.headers });
    }
    const etag = response.headers.get("etag");
    if (response.ok && etag && limit > 0) {
      if (!cache.has(key) && cache.size >= limit) cache.delete(cache.keys().next().value!);
      cache.set(key, { etag, body: await response.clone().text(), headers: [...response.headers] });
    }
    return response;
  }

  const client = createClient<paths>({
    baseUrl: base.origin,
    querySerializer: { array: { style: "form", explode: true } },
    fetch: async (request) => {
      const url = new URL(request.url);
      if (options.publicCache) {
        return revisionCachedResponse(url, options.publicCache, revalidate, async () => {
          const response = await fetcher(new URL("/api/v1/revision", base), {
            method: "GET", headers: { Accept: "application/json" }, cache: "no-store", signal: AbortSignal.timeout(timeoutMs),
          });
          if (!response.ok) throw new ApiError(response.status, "Authoritative revision is unavailable");
          const value = await response.json() as { datasetRevision: number; representationVersion:string };
          if (!Number.isSafeInteger(value.datasetRevision) || value.datasetRevision < 0) throw new ApiError(502, "Invalid authoritative revision");
          if(!/^[a-f0-9]{64}$/.test(value.representationVersion)) throw new ApiError(502,"Invalid authoritative representation version");
          return value;
        });
      }
      return revalidate(url);
    },
  });

  function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
    if (result.error || !result.response.ok) {
      const problem = (result.error && typeof result.error === "object" ? result.error : null) as ApiProblem | null;
      throw new ApiError(result.response.status, problem?.detail || problem?.title || `API request failed with ${result.response.status}`, problem);
    }
    if (result.data === undefined) throw new ApiError(502, "API returned no representation");
    return result.data;
  }

  return {
    overview(input: { platform: Platform; period: Period; q?: string; sort?: OverviewSort; direction?: SortDirection; limit?: number; cursor?: string }) {
      const q = (input.q ?? "").trim();
      if ([...(input.q ?? "")].length > 200) throw new RangeError("q must contain at most 200 characters");
      return client.GET("/api/v1/overview", { params: { query: { ...input, q: q || undefined, limit: Math.min(200, Math.max(1, input.limit ?? 50)) } } }).then(unwrap);
    },
    institution(legacyId: number, platform: Platform, period: Period) {
      return client.GET("/api/v1/institutions/{legacyId}", { params: { path: { legacyId }, query: { platform, period } } }).then(unwrap);
    },
    publication(legacyId: number | string, legacyType?: LegacyPublicationType) {
      return client.GET("/api/v1/publications/{legacyId}", { params: { path: { legacyId }, query: { legacyType } } }).then(unwrap);
    },
    account(legacyId: number | string, legacyType?: LegacyAccountType) {
      return client.GET("/api/v1/accounts/{legacyId}", { params: { path: { legacyId }, query: { legacyType } } }).then(unwrap);
    },
    accountPublications(legacyId: number | string, legacyType?: LegacyAccountType, cursor?: string) {
      return client.GET("/api/v1/accounts/{legacyId}/publications", { params: { path: { legacyId }, query: { legacyType, limit: 200, cursor } } }).then(unwrap);
    },
    institutionAccounts(legacyId: number, platform: Platform, cursor?: string) {
      return client.GET("/api/v1/institutions/{legacyId}/accounts", { params: { path: { legacyId }, query: { platform, limit: 200, cursor } } }).then(unwrap);
    },
    publicationHistory(legacyId: number | string, legacyType?: LegacyPublicationType, cursor?: string) {
      return client.GET("/api/v1/publications/{legacyId}/history", { params: { path: { legacyId }, query: { legacyType, limit: 2000, cursor } } }).then(unwrap);
    },
    comparisonCandidates(platform: Exclude<Platform, "all">, cursor?: string) {
      return client.GET("/api/v1/compare/candidates", { params: { query: { platform, limit: 200, cursor } } }).then(unwrap);
    },
    comparison(input: ComparisonRequest) {
      const channels = input.platform === "telegram" ? normalizeComparisonIds("channels", input.channels) : undefined;
      const institutions = input.platform === "telegram" ? undefined : normalizeComparisonIds("institutions", input.institutions);
      return client.GET("/api/v1/compare", { params: { query: { ...input, channels: channels && [...channels], institutions: institutions && [...institutions], institutionLimit: Math.min(COMPARISON_PAGE_SIZE, Math.max(1, input.institutionLimit ?? COMPARISON_PAGE_SIZE)) } } }).then(unwrap);
    },
    rating(input: ActivityRatingRequest) {
      return client.GET("/api/v1/rating", { params: { query: {
        platform: input.platform, period: input.period, channel_sort: input.channelSort,
        channel_direction: input.channelDirection, post_sort: input.postSort,
        post_direction: input.postDirection, entityLimit: Math.min(200, Math.max(1, input.entityLimit ?? 200)),
        ...(input.entityCursor ? { entityCursor: input.entityCursor } : {}),
      } } }).then(unwrap);
    },
  };
}

const nextPublicCache: PublicResponseCache = {
  async load(key, tags, produce) {
    const { unstable_cache } = await import("next/cache");
    return unstable_cache(produce, key, { tags, revalidate: 300 })();
  },
};
export const api = createApiClient({ publicCache: process.env.NEXT_PUBLIC_DATA_CACHE === "disabled" ? undefined : nextPublicCache });

function normalizeComparisonIds(parameter: "channels" | "institutions", value: readonly number[] | undefined): readonly number[] | undefined {
  if (value === undefined) return undefined;
  if (value.length === 0 || value.length > MAX_COMPARISON_INSTITUTIONS) throw new RangeError(`${parameter} must contain between 1 and ${MAX_COMPARISON_INSTITUTIONS} IDs`);
  for (const id of value) if (!Number.isSafeInteger(id) || id <= 0) throw new RangeError(`${parameter} IDs must be positive safe integers`);
  return [...new Set(value)];
}
