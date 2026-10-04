import { first, many, normalizePlatform, parsePositiveLegacyId, type QueryValue, type SearchParams } from "./params";
import type { Finding, Platform, SortDirection } from "./types";

export type FindingsMode = "all" | "institution";
export type FindingsPeriod = "1d" | "7d" | "30d";
export type FindingsSort = "interaction_index" | "view_index" | "interactions24" | "views24" | "erv24" | "published_at";
export type FindingsType = "text" | "photo" | "album" | "video" | "other";
export type FindingsGroup = "none" | "institution";

export const FINDINGS_PERIOD_OPTIONS = [
  { value: "1d", label: "24 ч", title: "Сутки" },
  { value: "7d", label: "7 д", title: "7 дней" },
  { value: "30d", label: "30 д", title: "30 дней" },
] as const satisfies readonly { value: FindingsPeriod; label: string; title: string }[];

export const FINDINGS_SORT_OPTIONS = [
  ["interaction_index", "Выше нормы"],
  ["view_index", "Выше нормы · просмотры"],
  ["interactions24", "Взаимодействия"],
  ["views24", "Просмотры"],
  ["erv24", "ERV"],
  ["published_at", "Новые"],
] as const satisfies readonly (readonly [FindingsSort, string])[];

export const FINDINGS_TYPE_OPTIONS = [
  ["text", "Текст"], ["photo", "Фото"], ["album", "Альбом"], ["video", "Видео"], ["other", "Прочее"],
] as const satisfies readonly (readonly [FindingsType, string])[];

export interface ParsedFindingsQuery {
  mode: FindingsMode;
  institution: number | null;
  platform: Platform;
  period: FindingsPeriod;
  types: FindingsType[];
  sort: FindingsSort;
  direction: SortDirection;
  group: FindingsGroup;
  q: string;
}

const PERIODS = new Set<string>(FINDINGS_PERIOD_OPTIONS.map((option) => option.value));
const SORTS = new Set<string>(FINDINGS_SORT_OPTIONS.map(([value]) => value));
const TYPES: readonly FindingsType[] = FINDINGS_TYPE_OPTIONS.map(([value]) => value);

export function normalizeFindingsQuery(params: SearchParams): ParsedFindingsQuery {
  const institution = parsePositiveLegacyId(first(params.institution) ?? "");
  const mode: FindingsMode = first(params.mode) === "institution" && institution !== null ? "institution" : "all";
  const period = first(params.period) ?? "";
  const sort = first(params.sort) ?? "";
  const requested = new Set(many(params.types));
  return {
    mode,
    institution: mode === "institution" ? institution : null,
    platform: normalizePlatform(params.platform, "all"),
    period: PERIODS.has(period) ? period as FindingsPeriod : "7d",
    types: TYPES.filter((value) => requested.has(value)),
    sort: SORTS.has(sort) ? sort as FindingsSort : "interaction_index",
    direction: first(params.direction) === "asc" ? "asc" : "desc",
    group: mode === "all" && first(params.group) === "institution" ? "institution" : "none",
    q: (first(params.q) ?? "").trim(),
  };
}

/** Выдача, которую страница открывает без параметров и которую греет прогрев кэша. */
export const DEFAULT_FINDINGS_QUERY: ParsedFindingsQuery = Object.freeze(normalizeFindingsQuery({}));

export function findingsHrefQuery(query: ParsedFindingsQuery): Record<string, QueryValue> {
  return {
    mode: query.mode === "institution" ? "institution" : undefined,
    institution: query.institution ?? undefined,
    platform: query.platform,
    period: query.period,
    types: query.types,
    sort: query.sort,
    direction: query.direction,
    group: query.group === "institution" ? "institution" : undefined,
    q: query.q || undefined,
  };
}

const indexFormat = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function formatIndex(value: number | null): string {
  return value === null ? "—" : `×${indexFormat.format(value)}`;
}

/** Не больше одной пометки на строку: возраст важнее уровня анализа. */
export function findingBadge(row: Finding, anomaliesVisible: boolean): string | null {
  if (row.preliminary && row.ageHours !== null) return `предварительно, ${row.ageHours} ч`;
  if (row.ageHours !== null && row.ageHours < 24) return `по ${row.ageHours}-му часу`;
  if (!anomaliesVisible) return null;
  if (row.anomalyLevel === 1) return "слабый сигнал";
  if (row.anomalyLevel === null) return "не проверен";
  return null;
}

export const INSTITUTION_STORAGE_KEY = "m-ranked-findings-institution";

export function rememberInstitution(storage: Pick<Storage, "setItem"> | null, id: number): void {
  try { storage?.setItem(INSTITUTION_STORAGE_KEY, String(id)); } catch { /* приватный режим: только удобство */ }
}

export function recallInstitution(storage: Pick<Storage, "getItem"> | null): number | null {
  try { return parsePositiveLegacyId(storage?.getItem(INSTITUTION_STORAGE_KEY) ?? ""); } catch { return null; }
}
