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

export const ACCOUNT_PUBLICATION_LIMIT = 100;
export const INSTITUTION_ACCOUNT_LIMIT = 50;
export const FULL_PUBLICATION_HISTORY_LIMIT = 3_000;

export type StatisticsView = "publications" | "entities";
export type StatisticsPublicationSort =
  | "erv"
  | "views"
  | "interactions"
  | "published_at";
export type StatisticsEntitySort =
  | "erv"
  | "median_interactions"
  | "interactions"
  | "views"
  | "publications";
export type SortDirection = "asc" | "desc";

export interface StatisticsRequest {
  view: StatisticsView;
  platform: Platform;
  period: Period;
  q?: string;
  publicationSort: StatisticsPublicationSort;
  publicationDirection: SortDirection;
  entitySort: StatisticsEntitySort;
  entityDirection: SortDirection;
  limit?: number;
  cursor?: string;
}

export type StatisticsEntity = components["schemas"]["StatisticsEntity"];

export type StatisticsPublication = components["schemas"]["StatisticsPublication"];

export type StatisticsPage = components["schemas"]["Statistics"];

export type PublicationView = components["schemas"]["Publication"];

export type ApiProblem = Partial<components["schemas"]["Problem"]>;

export type PublicationListItem = components["schemas"]["PublicationListItem"];
export type PublicationHistory = components["schemas"]["PublicationHistory"];
export type HistorySnapshot = components["schemas"]["HistorySnapshot"];
export type CollectorCoverage = components["schemas"]["CollectorCoverage"];
export type CollectorGap = components["schemas"]["CollectorGap"];
export type PublicationAnomalyAnalysis = components["schemas"]["PublicationAnomalyAnalysis"];
export type AccountAnomalyLevels = components["schemas"]["AccountAnomalyLevels"];
export type AnomalySignal = components["schemas"]["AnomalySignal"];
