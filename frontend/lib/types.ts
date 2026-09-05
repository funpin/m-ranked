export const PLATFORM_VALUES = ["all", "telegram", "vk", "max", "rutube"] as const;
export const PERIOD_VALUES = ["3h", "1d", "7d", "30d"] as const;

export type Platform = (typeof PLATFORM_VALUES)[number];
export type Period = (typeof PERIOD_VALUES)[number];
export type MetricValue = number | string | null;

export interface Metrics {
  totalReactions: MetricValue;
  totalViews: MetricValue;
  medianReactions: MetricValue;
  medianViews: MetricValue;
  sampleSize: number;
  coverage: MetricValue;
  quality: string | null;
}

export interface OverviewItem {
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
  subscriberCount: MetricValue;
  lastCheckedAt: string | null;
  lastErrorCode: string | null;
  statusCode: OverviewStatus;
  ratingRank: number | null;
  ratingScore: MetricValue;
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

export type OverviewStatus =
  | "no_account"
  | "all_accounts_disabled"
  | "last_poll_failed"
  | "polling"
  | "awaiting_first_poll"
  | "connected";

export interface OverviewMetric {
  total: MetricValue;
  median: MetricValue;
  previousTotal: MetricValue;
  previousMedian: MetricValue;
  totalTrend: MetricValue;
  medianTrend: MetricValue;
}

export interface OverviewAccount {
  accountId: string;
  legacyId: number | null;
  legacyRoute: string | null;
  platform: Exclude<Platform, "all">;
  canonicalExternalId: string;
  username: string | null;
  title: string | null;
  url: string | null;
  accessMode: string;
  enabled: boolean;
  subscriberCount: MetricValue;
  subscriberDisplay: string | null;
  subscriberObservedAt: string | null;
  latestPollStartedAt: string | null;
  latestPollCompletedAt: string | null;
  latestPollStatus: string | null;
  latestErrorCode: string | null;
}

export interface OverviewPage {
  items: OverviewItem[];
  nextCursor: string | null;
  datasetRevision: number;
  asOf: string | null;
}

export interface InstitutionView {
  institutionId: string;
  legacyId: number;
  canonicalName: string;
  shortName: string | null;
  platform: Platform;
  period: Period;
  metrics: Metrics;
  datasetRevision: number;
  asOf: string | null;
}

export interface CounterMetric {
  value: number | null;
  observedAt: string | null;
  quality: string | null;
}

export type LegacyPublicationType = "posts" | "platform_posts";
export type LegacyAccountType = "channels" | "platform_accounts";

export interface AccountView {
  accountId: string;
  legacyId: number;
  legacyType: LegacyAccountType;
  channelLegacyId: number | null;
  platformAccountLegacyId: number | null;
  institutionId: string;
  institutionLegacyId: number;
  institutionName: string;
  institutionShortName: string | null;
  platform: Exclude<Platform, "all">;
  canonicalExternalId: string;
  username: string | null;
  title: string | null;
  url: string | null;
  accessMode: string;
  enabled: boolean;
  publicationCount: number;
  latestObservedAt: string | null;
  datasetRevision: number;
  asOf: string | null;
}

export type ComparisonHorizon = 24 | 48 | 72 | 168 | 336;
export type ComparisonMetric = "views" | "reactions" | "comments" | "shares";
export type ComparisonAggregation = "sum" | "median";
export type ComparisonSelectionType = "channels" | "institutions";
export const MAX_COMPARISON_INSTITUTIONS = 50;

export interface ComparisonRequest {
  platform: Exclude<Platform, "all">;
  horizonHours: ComparisonHorizon;
  includePartial: boolean;
  metric: ComparisonMetric;
  aggregation: ComparisonAggregation;
  institutionLimit?: number;
  institutions?: readonly number[];
  channels?: readonly number[];
}

export interface ComparisonPoint {
  hourOffset: number;
  value: MetricValue;
  sampleSize: number;
  coverage: MetricValue;
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

export interface ComparisonView {
  cohortId: string;
  platform: Exclude<Platform, "all">;
  horizonHours: ComparisonHorizon;
  includePartial: boolean;
  metric: ComparisonMetric;
  aggregation: ComparisonAggregation;
  selectionType: ComparisonSelectionType;
  cohortSampleSize: number;
  series: ComparisonSeries[];
  datasetRevision: number;
  asOf: string | null;
}

export type ActivityRatingPlatform = Exclude<Platform, "all" | "max">;
export type ActivityRatingEntityType = "channels" | "institutions";
export type ActivityRatingChannelSort =
  | "average"
  | "total"
  | "engagement"
  | "views"
  | "subscribers";
export type ActivityRatingPostSort =
  | "reactions"
  | "subscriber_share"
  | "view_share"
  | "views"
  | "comments"
  | "shares"
  | "interactions";
export type SortDirection = "asc" | "desc";

export interface ActivityRatingRequest {
  platform: ActivityRatingPlatform;
  period: Period;
  channelSort: ActivityRatingChannelSort;
  channelDirection: SortDirection;
  postSort: ActivityRatingPostSort;
  postDirection: SortDirection;
  entityLimit?: number;
}

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
  averageReactions: MetricValue;
  averageViews: MetricValue;
  totalReactions: MetricValue;
  totalViews: MetricValue;
  totalComments: MetricValue;
  totalShares: MetricValue;
  totalInteractions: MetricValue;
  engagementRate: MetricValue;
  subscriberCount: MetricValue;
}

export interface ActivityRatingPublication {
  publicationId: string;
  legacyId: number | null;
  legacyType: LegacyPublicationType;
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
  views: MetricValue;
  reactions: MetricValue;
  comments: MetricValue;
  shares: MetricValue;
  interactions: MetricValue;
  subscriberShare: MetricValue;
  viewShare: MetricValue;
}

export interface RatingView {
  platform: ActivityRatingPlatform;
  period: Period;
  entityType: ActivityRatingEntityType;
  publicationLegacyType: LegacyPublicationType;
  channelSort: ActivityRatingChannelSort;
  channelDirection: SortDirection;
  postSort: ActivityRatingPostSort;
  postDirection: SortDirection;
  entities: ActivityRatingEntity[];
  publications: ActivityRatingPublication[];
  entityLimit: number;
  entitiesTruncated: boolean;
  datasetRevision: number;
  asOf: string | null;
}

export interface PublicationView {
  publicationId: string;
  legacyId: number;
  legacyType: LegacyPublicationType;
  institutionId: string;
  platform: Exclude<Platform, "all">;
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
  historyCompleteness: string;
  datasetRevision: number;
  asOf: string | null;
}

export interface ApiProblem {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
}
