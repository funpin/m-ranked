import type { components } from "../../contracts/openapi/m-ranked-v1-client";

export const PLATFORM_VALUES = ["all", "telegram", "vk", "max", "rutube"] as const;
export const PERIOD_VALUES = ["3h", "1d", "7d", "30d"] as const;

export type Platform = (typeof PLATFORM_VALUES)[number];
export type Period = (typeof PERIOD_VALUES)[number];
export type MetricValue = number | string | null;

export type Metrics = components["schemas"]["Metrics"];

export type OverviewItem = components["schemas"]["OverviewRow"];

export type OverviewStatus =
  | "no_account"
  | "all_accounts_disabled"
  | "last_poll_failed"
  | "polling"
  | "awaiting_first_poll"
  | "connected";

export type OverviewMetric = components["schemas"]["OverviewMetric"];

export type OverviewAccount = components["schemas"]["OverviewAccount"];

export type OverviewPage = components["schemas"]["OverviewPage"];

export type InstitutionView = components["schemas"]["Institution"];

export type CounterMetric = components["schemas"]["CounterMetric"];

export type LegacyPublicationType = "posts" | "platform_posts";
export type LegacyAccountType = "channels" | "platform_accounts";

export type AccountView = components["schemas"]["Account"];

export type ComparisonHorizon = 24 | 48 | 72 | 168 | 336;
export type ComparisonMetric = "views" | "reactions" | "comments" | "shares";
export type ComparisonAggregation = "sum" | "median";
export type ComparisonSelectionType = "channels" | "institutions";
export const MAX_COMPARISON_INSTITUTIONS = 2_000;
export const COMPARISON_PAGE_SIZE = 50;

export interface ComparisonRequest {
  platform: Exclude<Platform, "all">;
  horizonHours: ComparisonHorizon;
  includePartial: boolean;
  metric: ComparisonMetric;
  aggregation: ComparisonAggregation;
  institutionLimit?: number;
  selectionCursor?: string;
  institutions?: readonly number[];
  channels?: readonly number[];
}

export type ComparisonPoint = components["schemas"]["ComparisonPoint"];

export type ComparisonSeries = components["schemas"]["ComparisonSeries"];

export type ComparisonView = components["schemas"]["Comparison"];

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
  entityCursor?: string;
}

export type ActivityRatingEntity = components["schemas"]["ActivityRatingEntity"];

export type ActivityRatingPublication = components["schemas"]["ActivityRatingPublication"];

export type RatingView = components["schemas"]["Rating"];

export type PublicationView = components["schemas"]["Publication"];

export type ApiProblem = Partial<components["schemas"]["Problem"]>;

export type PublicationListItem = components["schemas"]["PublicationListItem"];
export type PublicationHistory = components["schemas"]["PublicationHistory"];
export type HistorySnapshot = components["schemas"]["HistorySnapshot"];
