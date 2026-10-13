import { first, many, normalizePlatform, parsePositiveLegacyId, type QueryValue, type SearchParams } from "./params";
import type { Finding, Platform, SortDirection } from "./types";

export type FindingsMode = "all" | "institution";
export type FindingsPeriod = "1d" | "7d" | "30d";
/** Раздел «Находок»: посты выше нормы или рейтинг аномальных постов. */
export type FindingsView = "above_norm" | "anomalous";
export type AboveNormSort = "interaction_index" | "view_index" | "comment_index" | "share_index"
  | "interactions24" | "views24" | "erv24" | "published_at";
export type AnomalousSort = "anomaly" | "anomaly_share" | "anomaly_volume" | "published_at";
export type FindingsSort = AboveNormSort | AnomalousSort;
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
  ["comment_index", "Обсуждаемые"],
  ["share_index", "Репостят"],
  ["interactions24", "Взаимодействия"],
  ["views24", "Просмотры"],
  ["erv24", "ERV"],
  ["published_at", "Новые"],
] as const satisfies readonly (readonly [AboveNormSort, string])[];

/** Сортировки рейтинга аномальных постов: по умолчанию — уровень, затем доля
 *  необычного прироста. */
export const ANOMALOUS_SORT_OPTIONS = [
  ["anomaly", "Сильнее аномалия"],
  ["anomaly_share", "Доля необычного прироста"],
  ["anomaly_volume", "Объём необычного прироста"],
  ["published_at", "Новые"],
] as const satisfies readonly (readonly [AnomalousSort, string])[];

export const FINDINGS_VIEW_OPTIONS = [
  { value: "above_norm", label: "Выше нормы", title: "Посты, сработавшие лучше обычного для своего аккаунта" },
  { value: "anomalous", label: "Аномальные посты", title: "Посты с самой необычной динамикой счётчиков" },
] as const satisfies readonly { value: FindingsView; label: string; title: string }[];

export const FINDINGS_TYPE_OPTIONS = [
  ["text", "Текст"], ["photo", "Фото"], ["album", "Альбом"], ["video", "Видео"], ["other", "Прочее"],
] as const satisfies readonly (readonly [FindingsType, string])[];

export interface ParsedFindingsQuery {
  view: FindingsView;
  /** Скрыть посты аккаунтов с устойчивыми аккаунтными находками. */
  clean: boolean;
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
const ANOMALOUS_SORTS = new Set<string>(ANOMALOUS_SORT_OPTIONS.map(([value]) => value));
const TYPES: readonly FindingsType[] = FINDINGS_TYPE_OPTIONS.map(([value]) => value);

export function normalizeFindingsQuery(params: SearchParams): ParsedFindingsQuery {
  const institution = parsePositiveLegacyId(first(params.institution) ?? "");
  const mode: FindingsMode = first(params.mode) === "institution" && institution !== null ? "institution" : "all";
  const period = first(params.period) ?? "";
  const sort = first(params.sort) ?? "";
  const requested = new Set(many(params.types));
  const platform = normalizePlatform(params.platform, "all");
  const view: FindingsView = first(params.view) === "anomalous" ? "anomalous" : "above_norm";
  const resolvedSort: FindingsSort = view === "anomalous"
    ? ANOMALOUS_SORTS.has(sort) ? sort as AnomalousSort : "anomaly"
    : SORTS.has(sort) && sortAvailable(sort as AboveNormSort, platform) ? sort as AboveNormSort : "interaction_index";
  return {
    view,
    clean: first(params.clean) === "1",
    mode,
    institution: mode === "institution" ? institution : null,
    platform,
    period: PERIODS.has(period) ? period as FindingsPeriod : "7d",
    types: TYPES.filter((value) => requested.has(value)),
    sort: resolvedSort,
    direction: first(params.direction) === "asc" ? "asc" : "desc",
    group: mode === "all" && first(params.group) === "institution" ? "institution" : "none",
    q: (first(params.q) ?? "").trim(),
  };
}

/** Выдача, которую страница открывает без параметров и которую греет прогрев кэша. */
export const DEFAULT_FINDINGS_QUERY: ParsedFindingsQuery = Object.freeze(normalizeFindingsQuery({}));

export function findingsHrefQuery(query: ParsedFindingsQuery): Record<string, QueryValue> {
  return {
    view: query.view === "anomalous" ? "anomalous" : undefined,
    clean: query.clean ? "1" : undefined,
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

/** Тот же отбор в другом разделе: сортировка у разделов своя и сбрасывается. */
export function viewHrefQuery(query: ParsedFindingsQuery, view: FindingsView): Record<string, QueryValue> {
  return { ...findingsHrefQuery(query), view: view === "anomalous" ? "anomalous" : undefined, sort: undefined, direction: undefined };
}

/** Комментарии отдают все площадки, кроме MAX; репосты — только ВКонтакте. */
function sortAvailable(sort: AboveNormSort, platform: Platform): boolean {
  if (sort === "comment_index") return platform !== "max";
  if (sort === "share_index") return platform === "all" || platform === "vk";
  return true;
}

export function sortOptionsFor(platform: Platform, view: FindingsView = "above_norm"): readonly (readonly [FindingsSort, string])[] {
  if (view === "anomalous") return ANOMALOUS_SORT_OPTIONS;
  return FINDINGS_SORT_OPTIONS.filter(([value]) => sortAvailable(value, platform));
}

/** Индекс, который показывает колонка: по выбранной мере «выше нормы». */
export function findingIndex(row: Finding, sort: FindingsSort): { value: number | null; norm: number | null; noun: string } {
  if (sort === "comment_index") return { value: row.commentIndex, norm: row.commentNorm, noun: "комментариев" };
  if (sort === "share_index") return { value: row.shareIndex, norm: row.shareNorm, noun: "репостов" };
  return { value: row.interactionIndex, norm: row.interactionNorm, noun: "взаимодействий" };
}

const PERIOD_DAYS: Record<FindingsPeriod, number> = { "1d": 1, "7d": 7, "30d": 30 };
const dayMonth = new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit" });

/** Окно выборки: период отсчитывается от момента данных, а не от «сейчас». */
export function periodRange(asOf: string, period: FindingsPeriod): string {
  const end = new Date(asOf);
  const start = new Date(end.getTime() - PERIOD_DAYS[period] * 86_400_000);
  return `${dayMonth.format(start)} – ${dayMonth.format(end)}`;
}

const VISIT_KEY = "m-ranked-findings-visit";

/** Момент прошлого визита. В пределах сессии он закреплён, чтобы
 *  перезагрузка не снимала пометки «новое»; в localStorage пишется текущий. */
export function previousVisit(local: Pick<Storage, "getItem" | "setItem"> | null,
  session: Pick<Storage, "getItem" | "setItem"> | null, now: number): number | null {
  try {
    const pinned = session?.getItem(VISIT_KEY);
    if (pinned !== null && pinned !== undefined) return pinned === "none" ? null : Number(pinned) || null;
    const stored = Number(local?.getItem(VISIT_KEY) ?? "");
    const previous = Number.isFinite(stored) && stored > 0 ? stored : null;
    session?.setItem(VISIT_KEY, previous === null ? "none" : String(previous));
    local?.setItem(VISIT_KEY, String(now));
    return previous;
  } catch {
    return null;
  }
}

export function isNewSince(row: Pick<Finding, "publishedAt">, visit: number | null): boolean {
  return visit !== null && row.publishedAt !== null && Date.parse(row.publishedAt) > visit;
}

const shareFormat = new Intl.NumberFormat("ru-RU", { style: "percent", maximumFractionDigits: 0 });
const METRIC_GENITIVE: Record<string, string> = {
  views: "просмотров", reactions: "реакций", comments: "комментариев", shares: "репостов",
};

/** «+1 000 просмотров · 83 % итога»: сколько и какая доля метрики пришла в участке признака. */
export function anomalyGrowthText(growth: number | null, share: number | null, metric: string | null,
  format: (value: number) => string): { headline: string; detail: string | null } {
  if (share === null || growth === null || metric === null) return { headline: "—", detail: null };
  return {
    headline: shareFormat.format(share),
    detail: `+${format(growth)} ${METRIC_GENITIVE[metric] ?? metric}`,
  };
}

/** Устойчивые (статус 2) находки аккаунта поста — первыми. */
export function hasPersistentFindings(row: { accountFindings: readonly { status: number }[] }): boolean {
  return row.accountFindings.some((item) => item.status === 2);
}
