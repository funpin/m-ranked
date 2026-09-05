import { MAX_COMPARISON_INSTITUTIONS } from "./types";
import type {
  AccountView,
  ActivityRatingRequest,
  ApiProblem,
  ComparisonRequest,
  ComparisonView,
  InstitutionView,
  LegacyAccountType,
  LegacyPublicationType,
  OverviewPage,
  Period,
  Platform,
  PublicationView,
  RatingView,
  SortDirection,
} from "./types";
import type { OverviewSort } from "./params";

type Fetcher = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

interface CacheEntry {
  etag: string;
  payload: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem: ApiProblem | null;

  constructor(status: number, message: string, problem: ApiProblem | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }
}

export interface ApiClientOptions {
  baseUrl?: string;
  fetcher?: Fetcher;
  timeoutMs?: number;
  cacheEntries?: number;
}

function normalizedBaseUrl(value: string): URL {
  const base = new URL(value);
  if (base.protocol !== "http:" && base.protocol !== "https:") {
    throw new Error("API_BASE_URL must use HTTP or HTTPS");
  }
  base.pathname = base.pathname.replace(/\/$/, "");
  return base;
}

async function problemFrom(response: Response): Promise<ApiProblem | null> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("json")) return null;
  try {
    return (await response.json()) as ApiProblem;
  } catch {
    return null;
  }
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = normalizedBaseUrl(
    options.baseUrl ?? process.env.API_BASE_URL ?? "http://127.0.0.1:8080",
  );
  const fetcher: Fetcher = options.fetcher ?? ((input, init) => fetch(input, init));
  const timeoutMs = options.timeoutMs ?? 8_000;
  const cacheLimit = options.cacheEntries ?? 128;
  const cache = new Map<string, CacheEntry>();

  type RequestValue = string | number | boolean | readonly number[] | undefined;

  async function request<T>(path: string, params: Record<string, RequestValue>): Promise<T> {
    const url = new URL(`/api/v1${path}`, baseUrl);
    for (const [key, value] of Object.entries(params)) {
      if (Array.isArray(value)) {
        for (const entry of value) url.searchParams.append(key, String(entry));
      } else if (value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
    const cacheKey = url.toString();
    const cached = cache.get(cacheKey);
    const headers = new Headers({ Accept: "application/json" });
    if (cached?.etag) headers.set("If-None-Match", cached.etag);

    let response: Response;
    try {
      response = await fetcher(url, {
        method: "GET",
        headers,
        cache: "no-store",
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (error) {
      throw new ApiError(0, "Spring API is unavailable", null);
    }

    if (response.status === 304) {
      if (!cached) throw new ApiError(502, "API returned 304 without a cached representation");
      return cached.payload as T;
    }
    if (!response.ok) {
      const problem = await problemFrom(response);
      throw new ApiError(
        response.status,
        problem?.detail || problem?.title || `API request failed with ${response.status}`,
        problem,
      );
    }

    const payload = (await response.json()) as T;
    const etag = response.headers.get("etag");
    if (etag) {
      if (!cache.has(cacheKey) && cache.size >= cacheLimit) {
        const oldest = cache.keys().next().value as string | undefined;
        if (oldest) cache.delete(oldest);
      }
      cache.set(cacheKey, { etag, payload });
    }
    return payload;
  }

  return {
    overview(input: {
      platform: Platform;
      period: Period;
      q?: string;
      sort?: OverviewSort;
      direction?: SortDirection;
      limit?: number;
      cursor?: string;
    }): Promise<OverviewPage> {
      return request("/overview", {
        platform: input.platform,
        period: input.period,
        q: (input.q ?? "").trim().slice(0, 200),
        sort: input.sort,
        direction: input.direction,
        limit: Math.min(200, Math.max(1, input.limit ?? 50)),
        cursor: input.cursor,
      });
    },

    institution(legacyId: number, platform: Platform, period: Period): Promise<InstitutionView> {
      return request(`/institutions/${legacyId}`, { platform, period });
    },

    publication(legacyId: number, legacyType: LegacyPublicationType): Promise<PublicationView> {
      return request(`/publications/${legacyId}`, { legacyType });
    },

    account(legacyId: number, legacyType: LegacyAccountType): Promise<AccountView> {
      return request(`/accounts/${legacyId}`, { legacyType });
    },

    comparison(input: ComparisonRequest): Promise<ComparisonView> {
      const { channels, institutions } = normalizeComparisonSelection(input);
      return request("/compare", {
        platform: input.platform,
        horizonHours: input.horizonHours,
        includePartial: input.includePartial,
        metric: input.metric,
        aggregation: input.aggregation,
        institutionLimit: Math.min(
          MAX_COMPARISON_INSTITUTIONS,
          Math.max(1, input.institutionLimit ?? MAX_COMPARISON_INSTITUTIONS),
        ),
        institutions,
        channels,
      });
    },

    rating(input: ActivityRatingRequest): Promise<RatingView> {
      return request("/rating", {
        platform: input.platform,
        period: input.period,
        channel_sort: input.channelSort,
        channel_direction: input.channelDirection,
        post_sort: input.postSort,
        post_direction: input.postDirection,
        entityLimit: Math.min(200, Math.max(1, input.entityLimit ?? 200)),
      });
    },
  };
}

export const api = createApiClient();

function normalizeComparisonIds(
  parameter: "channels" | "institutions",
  value: readonly number[] | undefined,
): readonly number[] | undefined {
  if (value === undefined) return undefined;
  if (value.length === 0 || value.length > MAX_COMPARISON_INSTITUTIONS) {
    throw new RangeError(
      `${parameter} must contain between 1 and ${MAX_COMPARISON_INSTITUTIONS} IDs`,
    );
  }
  const unique = new Set<number>();
  for (const legacyId of value) {
    if (!Number.isSafeInteger(legacyId) || legacyId <= 0) {
      throw new RangeError(`${parameter} IDs must be positive safe integers`);
    }
    unique.add(legacyId);
  }
  return [...unique];
}

function normalizeComparisonSelection(input: ComparisonRequest): {
  channels: readonly number[] | undefined;
  institutions: readonly number[] | undefined;
} {
  const telegram = input.platform === "telegram";
  return {
    channels: telegram ? normalizeComparisonIds("channels", input.channels) : undefined,
    institutions: telegram
      ? undefined
      : normalizeComparisonIds("institutions", input.institutions),
  };
}
