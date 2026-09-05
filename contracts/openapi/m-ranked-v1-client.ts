// Generated from m-ranked-v1.yaml. Do not edit independently of the source contract.
// Source-SHA256: 6ea694e90c05eac6f572eabeec9821dca7cb6c0e3173b2bf72ea764275ddc181

export type Platform = "all" | "telegram" | "vk" | "max" | "rutube";
export type ConcretePlatform = Exclude<Platform, "all">;
export type Period = "3h" | "1d" | "7d" | "30d";
export type Metric = "views" | "reactions" | "comments" | "shares";
export type Aggregation = "sum" | "median";
export type ComparisonSelectionType = "channels" | "institutions";
export type AccountLegacyType = "channels" | "platform_accounts";
export type PublicationLegacyType = "posts" | "platform_posts";
export type RunStatus = "pending" | "running" | "succeeded" | "partial" | "failed" | "skipped" | "cancelled";

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string;
}

export interface Liveness {
  status: "UP";
}

export interface Readiness {
  status: "UP" | "DOWN";
  datasetRevision?: number;
}

export interface Metrics {
  totalReactions: number | null;
  totalViews: number | null;
  medianReactions: number | null;
  medianViews: number | null;
  sampleSize: number;
  coverage: number | null;
  quality: string | null;
}

export interface OverviewRow {
  entityId: string;
  entityType: "channels" | "institutions";
  legacyId: number;
  legacyRoute: string | null;
  institutionId: string;
  institutionLegacyId: number;
  canonicalName: string;
  shortName: string | null;
  platform: Platform;
  period: Period;
  accounts: OverviewAccount[];
  accountCount: number;
  enabledAccountCount: number;
  connectedPlatformCount: number;
  subscriberCount: number | null;
  lastCheckedAt: string | null;
  lastErrorCode: string | null;
  statusCode: "no_account" | "all_accounts_disabled" | "last_poll_failed" | "polling" | "awaiting_first_poll" | "connected";
  ratingRank: number | null;
  ratingScore: number | null;
  ratingPeriod: string | null;
  ratingFetchedAt: string | null;
  totalPublicationCount: number | null;
  activityPublicationCount: number | null;
  newPublicationCount: number | null;
  views: OverviewMetric;
  reactions: OverviewMetric;
  comments: OverviewMetric;
  shares: OverviewMetric;
  asOf: string;
}

export interface OverviewMetric {
  total: number | null;
  median: number | null;
  previousTotal: number | null;
  previousMedian: number | null;
  totalTrend: number | null;
  medianTrend: number | null;
}

export interface OverviewAccount {
  accountId: string;
  legacyId: number | null;
  legacyRoute: string | null;
  platform: ConcretePlatform;
  canonicalExternalId: string;
  username: string | null;
  title: string | null;
  url: string | null;
  accessMode: string;
  enabled: boolean;
  subscriberCount: number | null;
  subscriberDisplay: string | null;
  subscriberObservedAt: string | null;
  latestPollStartedAt: string | null;
  latestPollCompletedAt: string | null;
  latestPollStatus: string | null;
  latestErrorCode: string | null;
}

export interface OverviewPage {
  items: OverviewRow[];
  nextCursor: string | null;
  datasetRevision: number;
  asOf: string;
}

export interface Institution {
  institutionId: string;
  legacyId: number;
  canonicalName: string;
  shortName: string | null;
  platform: Platform;
  period: Period;
  metrics: Metrics;
  datasetRevision: number;
  asOf: string;
}

export interface CounterMetric {
  value: number | null;
  observedAt: string | null;
  quality: string | null;
}

export interface Publication {
  publicationId: string;
  legacyId: number;
  legacyType: PublicationLegacyType;
  institutionId: string;
  platform: ConcretePlatform;
  publishedAt: string;
  publicationType: string;
  deletedAt: string | null;
  views: CounterMetric;
  reactions: CounterMetric;
  comments: CounterMetric;
  shares: CounterMetric;
  quality: string | null;
  intervalUncertain: boolean;
  synthetic: boolean;
  historyCompleteness: string | null;
  datasetRevision: number;
  asOf: string;
}

export type ActivityRatingPlatform = "telegram" | "vk" | "rutube";
export type ActivityRatingEntityType = "channels" | "institutions";
export type ActivityRatingChannelSort = "average" | "total" | "engagement" | "views" | "subscribers";
export type ActivityRatingPostSort = "reactions" | "subscriber_share" | "view_share" | "views" | "comments" | "shares" | "interactions";

export interface ActivityRatingEntity {
  entityId: string;
  entityType: ActivityRatingEntityType;
  legacyId: number;
  legacyRoute: string;
  institutionId: string;
  institutionLegacyId: number | null;
  canonicalName: string;
  shortName: string | null;
  username: string | null;
  title: string | null;
  publicationCount: number;
  averageReactions: number | null;
  averageViews: number | null;
  totalReactions: number;
  totalViews: number | null;
  totalComments: number | null;
  totalShares: number | null;
  totalInteractions: number | null;
  engagementRate: number | null;
  subscriberCount: number | null;
}

export interface ActivityRatingPublication {
  publicationId: string;
  legacyId: number | null;
  legacyType: PublicationLegacyType;
  legacyRoute: string | null;
  institutionId: string;
  institutionLegacyId: number;
  institutionCanonicalName: string;
  institutionShortName: string | null;
  accountId: string;
  accountLegacyId: number | null;
  accountUsername: string | null;
  accountTitle: string | null;
  externalId: string | null;
  publicUrl: string | null;
  publishedAt: string;
  deletedAt: string | null;
  joint: boolean;
  additionalAuthorCount: number;
  repost: boolean;
  views: number | null;
  reactions: number | null;
  comments: number | null;
  shares: number | null;
  interactions: number | null;
  subscriberShare: number | null;
  viewShare: number | null;
}

export interface Rating {
  platform: ActivityRatingPlatform;
  period: Period;
  entityType: ActivityRatingEntityType;
  publicationLegacyType: PublicationLegacyType;
  channelSort: ActivityRatingChannelSort;
  channelDirection: "asc" | "desc";
  postSort: ActivityRatingPostSort;
  postDirection: "asc" | "desc";
  entities: ActivityRatingEntity[];
  publications: ActivityRatingPublication[];
  entityLimit: number;
  entitiesTruncated: boolean;
  datasetRevision: number;
  asOf: string;
}

export interface ComparisonPoint {
  hourOffset: number;
  value: number | null;
  sampleSize: number;
  coverage: number;
  quality: string;
}

export interface ComparisonSeries {
  selectionId: string;
  selectionType: ComparisonSelectionType;
  selectionLegacyId: number;
  selectionLabel: string;
  institutionId: string;
  legacyId: number;
  canonicalName: string;
  shortName: string | null;
  primaryCohortSize: number;
  engagementCohortSize: number;
  points: ComparisonPoint[];
  engagementPoints: ComparisonPoint[];
}

export interface Comparison {
  cohortId: string;
  platform: ConcretePlatform;
  horizonHours: 24 | 48 | 72 | 168 | 336;
  includePartial: boolean;
  metric: Metric;
  aggregation: Aggregation;
  selectionType: ComparisonSelectionType;
  cohortSampleSize: number;
  series: ComparisonSeries[];
  datasetRevision: number;
  asOf: string;
}

export interface Account {
  accountId: string;
  legacyId: number;
  legacyType: AccountLegacyType;
  channelLegacyId: number | null;
  platformAccountLegacyId: number | null;
  institutionId: string;
  institutionLegacyId: number;
  institutionName: string;
  institutionShortName: string | null;
  platform: ConcretePlatform;
  canonicalExternalId: string;
  username: string | null;
  title: string | null;
  url: string | null;
  accessMode: string;
  enabled: boolean;
  publicationCount: number;
  latestObservedAt: string | null;
  datasetRevision: number;
  asOf: string;
}

export interface AdminCsrf {
  headerName: "X-XSRF-TOKEN";
  parameterName: "_csrf";
  token: string;
}

export interface AdminJob {
  jobId: string;
  kind: "collection";
  platform: ConcretePlatform;
  scheduledAt: string;
  startedAt: string;
  completedAt: string | null;
  status: RunStatus;
  accountCount: number;
  errorCount: number;
  correlationId: string;
}

export interface AdminJobPage {
  items: AdminJob[];
}

export interface AdminAccountResult {
  resultId: number;
  platformAccountId: string;
  startedAt: string;
  completedAt: string | null;
  status: RunStatus;
  discoveredCount: number;
  snapshotCount: number;
  sanitizedErrorCode: string | null;
}

export interface AdminJobDetail {
  job: AdminJob;
  accountResults: AdminAccountResult[];
  accountResultsTruncated: boolean;
}

export interface AdminSetEnabledRequest {
  enabled: boolean;
  expectedRowVersion: number;
}

export interface AdminPlatformAccountState {
  accountId: string;
  platform: ConcretePlatform;
  enabled: boolean;
  rowVersion: number;
  updatedAt: string;
}

export interface AdminSetEnabledResponse {
  account: AdminPlatformAccountState;
  changed: boolean;
  datasetRevision: number | null;
  correlationId: string;
  outcome: "updated" | "idempotent";
}

export interface ApiResponse<T> {
  status: number;
  data: T | null;
  etag: string | null;
}

export interface ConditionalRequest {
  ifNoneMatch?: string;
  signal?: AbortSignal;
}

export interface AdminRequestOptions {
  authorization: string;
  csrfToken?: string;
  correlationId?: string;
  signal?: AbortSignal;
}

export class MRankedApiError extends Error {
  constructor(public readonly problem: Problem) {
    super(problem.detail);
    this.name = "MRankedApiError";
  }
}

type QueryScalar = string | number | boolean;
type QueryValue = QueryScalar | readonly QueryScalar[] | undefined;
type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export class MRankedApiClient {
  constructor(
    private readonly baseUrl = "",
    private readonly fetchImpl: FetchLike = fetch,
  ) {}

  getLiveness(options: ConditionalRequest = {}): Promise<ApiResponse<Liveness>> {
    return this.getJson("/api/v1/health/live", {}, options, [200]);
  }

  getReadiness(options: ConditionalRequest = {}): Promise<ApiResponse<Readiness>> {
    return this.getJson("/api/v1/health/ready", {}, options, [200, 503]);
  }

  async getCustomEmoji(
    emojiId: string,
    options: Pick<ConditionalRequest, "signal"> = {},
  ): Promise<Response> {
    const response = await this.fetchImpl(
      this.url(`/api/v1/emoji/${encodeURIComponent(emojiId)}`, {}),
      {
        headers: { Accept: "image/webp,image/png,image/gif,image/jpeg,*/*" },
        signal: options.signal,
      },
    );
    if (response.status !== 200) await this.raise(response);
    return response;
  }

  getOverview(
    query: {
      platform?: Platform;
      period?: Period;
      q?: string;
      sort?: "name" | "median_reactions" | "m_rating" | "reactions" | "views" | "posts" | "subscribers" | "coverage" | "accounts";
      direction?: "asc" | "desc";
      limit?: number;
      cursor?: string;
    } = {},
    options: ConditionalRequest = {},
  ): Promise<ApiResponse<OverviewPage>> {
    return this.getJson("/api/v1/overview", query, options, [200, 304]);
  }

  getInstitution(
    legacyId: number,
    query: { platform?: Platform; period?: Period } = {},
    options: ConditionalRequest = {},
  ): Promise<ApiResponse<Institution>> {
    return this.getJson(`/api/v1/institutions/${legacyId}`, query, options, [200, 304]);
  }

  getPublication(
    legacyId: number,
    query: { legacyType?: PublicationLegacyType } = {},
    options: ConditionalRequest = {},
  ): Promise<ApiResponse<Publication>> {
    return this.getJson(`/api/v1/publications/${legacyId}`, query, options, [200, 304]);
  }

  getRating(
    query: {
      platform?: ActivityRatingPlatform;
      period?: Period;
      channel_sort?: ActivityRatingChannelSort;
      channel_direction?: "asc" | "desc";
      post_sort?: ActivityRatingPostSort;
      post_direction?: "asc" | "desc";
      entityLimit?: number;
    } = {},
    options: ConditionalRequest = {},
  ): Promise<ApiResponse<Rating>> {
    return this.getJson("/api/v1/rating", query, options, [200, 304]);
  }

  getComparison(
    query: {
      platform?: ConcretePlatform;
      horizonHours?: 24 | 48 | 72 | 168 | 336;
      includePartial?: boolean;
      metric?: Metric;
      aggregation?: Aggregation;
      institutionLimit?: number;
      channels?: readonly number[];
      institutions?: readonly number[];
    } = {},
    options: ConditionalRequest = {},
  ): Promise<ApiResponse<Comparison>> {
    return this.getJson("/api/v1/compare", query, options, [200, 304]);
  }

  getAccount(
    legacyId: number,
    query: { legacyType?: AccountLegacyType } = {},
    options: ConditionalRequest = {},
  ): Promise<ApiResponse<Account>> {
    return this.getJson(`/api/v1/accounts/${legacyId}`, query, options, [200, 304]);
  }

  async streamPublicationCsv(
    query: { platform?: Platform } = {},
    options: Pick<ConditionalRequest, "signal"> = {},
  ): Promise<Response> {
    const response = await this.fetchImpl(this.url("/api/v1/exports/publications.csv", query), {
      headers: { Accept: "text/csv" },
      signal: options.signal,
    });
    if (response.status !== 200) await this.raise(response);
    return response;
  }

  getAdminCsrf(options: AdminRequestOptions): Promise<ApiResponse<AdminCsrf>> {
    return this.adminJson("GET", "/api/v1/admin/csrf", {}, options);
  }

  getAdminJobs(
    options: AdminRequestOptions,
    query: { platform?: ConcretePlatform; status?: RunStatus; limit?: number } = {},
  ): Promise<ApiResponse<AdminJobPage>> {
    return this.adminJson("GET", "/api/v1/admin/jobs", query, options);
  }

  getAdminJob(
    jobId: string,
    options: AdminRequestOptions,
    query: { accountResultLimit?: number } = {},
  ): Promise<ApiResponse<AdminJobDetail>> {
    return this.adminJson(
      "GET",
      `/api/v1/admin/jobs/${encodeURIComponent(jobId)}`,
      query,
      options,
    );
  }

  getAdminPlatformAccount(
    accountId: string,
    options: AdminRequestOptions,
  ): Promise<ApiResponse<AdminPlatformAccountState>> {
    return this.adminJson(
      "GET",
      `/api/v1/admin/platform-accounts/${encodeURIComponent(accountId)}`,
      {},
      options,
    );
  }

  setAdminPlatformAccountEnabled(
    accountId: string,
    command: AdminSetEnabledRequest,
    options: AdminRequestOptions,
  ): Promise<ApiResponse<AdminSetEnabledResponse>> {
    return this.adminJson(
      "PUT",
      `/api/v1/admin/platform-accounts/${encodeURIComponent(accountId)}/enabled`,
      {},
      options,
      command,
    );
  }

  private async getJson<T>(
    path: string,
    query: object,
    options: ConditionalRequest,
    acceptedStatuses: number[],
  ): Promise<ApiResponse<T>> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (options.ifNoneMatch) headers["If-None-Match"] = options.ifNoneMatch;
    const response = await this.fetchImpl(this.url(path, query), {
      headers,
      signal: options.signal,
    });
    if (!acceptedStatuses.includes(response.status)) await this.raise(response);
    return {
      status: response.status,
      data: response.status === 304 ? null : (await response.json()) as T,
      etag: response.headers.get("etag"),
    };
  }

  private async adminJson<T>(
    method: "GET" | "PUT",
    path: string,
    query: object,
    options: AdminRequestOptions,
    body?: object,
  ): Promise<ApiResponse<T>> {
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: options.authorization,
    };
    if (options.csrfToken) headers["X-XSRF-TOKEN"] = options.csrfToken;
    if (options.correlationId) headers["X-Correlation-Id"] = options.correlationId;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const response = await this.fetchImpl(this.url(path, query), {
      method,
      headers,
      cache: "no-store",
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: options.signal,
    });
    if (response.status !== 200) await this.raise(response);
    return {
      status: response.status,
      data: await response.json() as T,
      etag: response.headers.get("etag"),
    };
  }

  private url(path: string, query: object): string {
    const parameters = new URLSearchParams();
    Object.entries(query as Record<string, QueryValue>)
      .sort(([left], [right]) => left.localeCompare(right))
      .forEach(([key, value]) => {
        if (Array.isArray(value)) {
          value.forEach((entry) => parameters.append(key, String(entry)));
        } else if (value !== undefined) {
          parameters.set(key, String(value));
        }
      });
    const suffix = parameters.size === 0 ? "" : `?${parameters.toString()}`;
    return `${this.baseUrl}${path}${suffix}`;
  }

  private async raise(response: Response): Promise<never> {
    let problem: Problem;
    try {
      problem = await response.json() as Problem;
    } catch {
      problem = {
        type: "about:blank",
        title: "HTTP request failed",
        status: response.status,
        detail: response.statusText,
        instance: response.url,
      };
    }
    throw new MRankedApiError(problem);
  }
}
