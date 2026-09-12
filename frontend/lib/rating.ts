import { first, normalizePlatform, type SearchParams, type SearchValue } from "./params";
import { PERIOD_VALUES } from "./types";
import type {
  ActivityRatingChannelSort,
  ActivityRatingPostSort,
  Period,
  Platform,
  SortDirection,
} from "./types";

const TELEGRAM_CHANNEL_SORTS = new Set<ActivityRatingChannelSort>([
  "average", "total", "engagement", "subscribers",
]);
const PLATFORM_CHANNEL_SORTS = new Set<ActivityRatingChannelSort>([
  "average", "total", "engagement", "views", "subscribers",
]);
const TELEGRAM_POST_SORTS = new Set<ActivityRatingPostSort>([
  "reactions", "subscriber_share", "view_share", "views",
]);
const VK_POST_SORTS = new Set<ActivityRatingPostSort>([
  "reactions", "views", "comments", "shares", "interactions", "view_share",
]);
const RUTUBE_POST_SORTS = new Set<ActivityRatingPostSort>([
  "reactions", "views", "comments", "interactions", "view_share",
]);

export interface ParsedRatingQuery {
  platform: Platform;
  period: Period;
  channelSort: ActivityRatingChannelSort;
  channelDirection: SortDirection;
  postSort: ActivityRatingPostSort;
  postDirection: SortDirection;
}
export function normalizeRatingPeriod(value: SearchValue): Period {
  const raw = first(value);
  if (raw === undefined) return "30d";
  const normalized = raw.trim().toLowerCase();
  return PERIOD_VALUES.includes(normalized as Period) ? normalized as Period : "1d";
}

export function normalizeRatingQuery(params: SearchParams): ParsedRatingQuery {
  const platform = normalizePlatform(params.platform, "telegram");
  const telegram = platform === "telegram";
  const channelSorts = telegram ? TELEGRAM_CHANNEL_SORTS : PLATFORM_CHANNEL_SORTS;
  const postSorts = telegram
    ? TELEGRAM_POST_SORTS
    : platform === "vk" ? VK_POST_SORTS : RUTUBE_POST_SORTS;
  const suppliedChannelSort = first(params.channel_sort) as ActivityRatingChannelSort | undefined;
  const suppliedPostSort = first(params.post_sort) as ActivityRatingPostSort | undefined;
  return {
    platform,
    period: normalizeRatingPeriod(params.period),
    channelSort: suppliedChannelSort && channelSorts.has(suppliedChannelSort)
      ? suppliedChannelSort : "engagement",
    channelDirection: direction(params.channel_direction),
    postSort: suppliedPostSort === undefined
      ? "view_share"
      : postSorts.has(suppliedPostSort)
        ? suppliedPostSort
        : telegram ? "reactions" : "view_share",
    postDirection: direction(params.post_direction),
  };
}

function direction(value: SearchValue): SortDirection {
  const normalized = first(value);
  return normalized === "asc" || normalized === "desc" ? normalized : "desc";
}
