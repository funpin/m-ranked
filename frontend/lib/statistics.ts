import { first, normalizePlatform, type SearchParams, type SearchValue } from "./params";
import { PERIOD_VALUES } from "./types";
import type {
  Period,
  Platform,
  SortDirection,
  StatisticsEntitySort,
  StatisticsPublicationSort,
  StatisticsView,
} from "./types";

const PUBLICATION_SORTS = new Set<StatisticsPublicationSort>([
  "erv", "views", "interactions", "published_at",
]);
const ENTITY_SORTS = new Set<StatisticsEntitySort>([
  "erv", "median_interactions", "interactions", "views", "publications",
]);

export interface ParsedStatisticsQuery {
  view: StatisticsView;
  platform: Platform;
  period: Period;
  q: string;
  publicationSort: StatisticsPublicationSort;
  publicationDirection: SortDirection;
  entitySort: StatisticsEntitySort;
  entityDirection: SortDirection;
}

export function normalizeStatisticsQuery(params: SearchParams): ParsedStatisticsQuery {
  const platform = normalizePlatform(params.platform, "all");
  const suppliedView = first(params.view);
  const period = first(params.period)?.trim().toLowerCase();
  const requestedPublicationSort = first(params.publication_sort);
  const publicationSort = (requestedPublicationSort === "reactions" ? "interactions" : requestedPublicationSort) as StatisticsPublicationSort | undefined;
  const entitySort = first(params.entity_sort) as StatisticsEntitySort | undefined;
  return {
    view: platform === "all" ? "publications" : suppliedView === "entities" ? "entities" : "publications",
    platform,
    period: period && PERIOD_VALUES.includes(period as Period) ? period as Period : "30d",
    q: (first(params.q) ?? "").trim(),
    publicationSort: publicationSort && PUBLICATION_SORTS.has(publicationSort) ? publicationSort : "erv",
    publicationDirection: direction(params.publication_direction),
    entitySort: entitySort && ENTITY_SORTS.has(entitySort) ? entitySort : "erv",
    entityDirection: direction(params.entity_direction),
  };
}

function direction(value: SearchValue): SortDirection {
  return first(value) === "asc" ? "asc" : "desc";
}

export function statisticsHrefQuery(query: ParsedStatisticsQuery) {
  return {
    view: query.platform === "all" ? undefined : query.view,
    platform: query.platform,
    period: query.period,
    q: query.q || undefined,
    publication_sort: query.publicationSort,
    publication_direction: query.publicationDirection,
    entity_sort: query.entitySort,
    entity_direction: query.entityDirection,
  };
}
