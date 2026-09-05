import {
  PERIOD_VALUES,
  PLATFORM_VALUES,
  MAX_COMPARISON_INSTITUTIONS,
  type Period,
  type Platform,
} from "./types";

export type SearchValue = string | string[] | undefined;
export type SearchParams = Record<string, SearchValue>;

export type OverviewSort =
  | "name"
  | "median_reactions"
  | "reactions"
  | "views"
  | "m_rating"
  | "posts"
  | "subscribers"
  | "coverage"
  | "accounts";

export function first(value: SearchValue): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function many(value: SearchValue): string[] {
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

export function comparisonSelectionIsExplicit(submitted: SearchValue): boolean {
  return first(submitted) === "true";
}

export type ComparisonSelectionIssue =
  | "invalid"
  | "too_many";

export interface ParsedComparisonSelection {
  ids: number[];
  issue: ComparisonSelectionIssue | null;
}

export interface ParsedComparisonQuerySelection extends ParsedComparisonSelection {
  explicit: boolean;
  type: "channels" | "institutions";
}

export function comparisonPlatformIsPending(
  platform: Platform,
): platform is Extract<Platform, "max" | "all"> {
  return platform === "max" || platform === "all";
}

export function parseComparisonQuerySelection(
  platform: Platform,
  submitted: SearchValue,
  channels: SearchValue,
  institutions: SearchValue,
): ParsedComparisonQuerySelection {
  const type = platform === "telegram" ? "channels" : "institutions";
  const explicit = comparisonSelectionIsExplicit(submitted);
  if (!explicit) return { explicit, type, ids: [], issue: null };
  const parsed = parseComparisonSelection(many(
    type === "channels" ? channels : institutions,
  ));
  return { explicit, type, ...parsed };
}

export function parseComparisonSelection(values: readonly string[]): ParsedComparisonSelection {
  if (values.length > MAX_COMPARISON_INSTITUTIONS) {
    return { ids: [], issue: "too_many" };
  }
  const ids: number[] = [];
  const unique = new Set<number>();
  for (const value of values) {
    const legacyId = parsePositiveLegacyId(value);
    if (legacyId === null) return { ids: [], issue: "invalid" };
    if (!unique.has(legacyId)) {
      unique.add(legacyId);
      ids.push(legacyId);
    }
  }
  return { ids, issue: null };
}

export function defaultComparisonSelection(ids: readonly number[]): number[] {
  return ids.slice(0, MAX_COMPARISON_INSTITUTIONS);
}

export function parsePositiveLegacyId(value: string): number | null {
  if (!/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

export function normalizePlatform(value: SearchValue, fallback: Platform = "telegram"): Platform {
  const normalized = (first(value) ?? "").trim().toLocaleLowerCase("ru");
  const aliased = normalized === "tg" ? "telegram" : normalized === "общий" ? "all" : normalized;
  return PLATFORM_VALUES.includes(aliased as Platform) ? (aliased as Platform) : fallback;
}

export function normalizePeriod(value: SearchValue, fallback: Period = "1d"): Period {
  const normalized = (first(value) ?? "").trim().toLowerCase();
  return PERIOD_VALUES.includes(normalized as Period) ? (normalized as Period) : fallback;
}

export function normalizeSort(value: SearchValue, platform: Platform): OverviewSort {
  const normalized = first(value);
  const accepted: OverviewSort[] = platform === "all"
    ? ["name", "m_rating", "coverage", "accounts"]
    : ["name", "median_reactions", "m_rating", "reactions", "views", "posts", "subscribers"];
  return accepted.includes(normalized as OverviewSort)
    ? (normalized as OverviewSort)
    : platform === "all" ? "m_rating" : "median_reactions";
}

export function normalizeDirection(value: SearchValue, sort: OverviewSort): "asc" | "desc" {
  const normalized = first(value);
  if (normalized === "asc" || normalized === "desc") return normalized;
  return sort === "name" ? "asc" : "desc";
}

export function normalizeHistoryLimit(value: SearchValue): number {
  const raw = first(value);
  if (raw === undefined) return 100;
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed >= 50 && parsed <= 1_000 ? parsed : 100;
}

export function legacyPlatformDecision(
  value: SearchValue,
  actualPlatform: Exclude<Platform, "all">,
  allowAll = false,
): "absent" | "redirect" | "not_found" {
  if (first(value) === undefined) return "absent";
  const platform = normalizePlatform(value);
  return platform === actualPlatform || (allowAll && platform === "all")
    ? "redirect"
    : "not_found";
}

export function metricNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function comparePeriod(value: SearchValue): {
  hours: 24 | 48 | 72 | 168 | 336;
  apiPeriod: Period;
} {
  const parsed = Number(first(value));
  const hours = ([24, 48, 72, 168, 336] as const).includes(parsed as never)
    ? (parsed as 24 | 48 | 72 | 168 | 336)
    : 72;
  const apiPeriod: Period = hours === 24 ? "1d" : hours <= 168 ? "7d" : "30d";
  return { hours, apiPeriod };
}

type QueryValue = string | number | readonly (string | number)[] | undefined;

export function queryHref(pathname: string, values: Record<string, QueryValue>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (Array.isArray(value)) {
      for (const entry of value) query.append(key, String(entry));
    } else if (value !== undefined && value !== "") {
      query.set(key, String(value));
    }
  }
  const suffix = query.toString();
  return suffix ? `${pathname}?${suffix}` : pathname;
}
