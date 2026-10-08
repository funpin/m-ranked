import type { components } from "../../contracts/openapi/m-ranked-v1-client";

/** Всё, что рисует страница сравнения, приходит одним ответом, а разрезы
 *  (площадка, мера, выделенные вузы) считаются здесь, в браузере: смена
 *  вкладки не ходит на сервер и не ждёт. */
export type Dashboard = components["schemas"]["ComparisonDashboard"];
export type DashboardStat = components["schemas"]["ComparisonDashboardStat"];
export type DashboardPlatform = "all" | "telegram" | "vk" | "max" | "rutube";
export type DashboardPeriod = "7d" | "30d";

export const DASHBOARD_PLATFORMS: readonly DashboardPlatform[] = ["all", "telegram", "vk", "max", "rutube"];
export const NETWORKS = ["telegram", "vk", "max", "rutube"] as const;
export type Network = (typeof NETWORKS)[number];

export const PLATFORM_NAMES: Record<DashboardPlatform, string> = {
  all: "Все соцсети", telegram: "Telegram", vk: "ВКонтакте", max: "MAX", rutube: "Rutube",
};
/** «нет аккаунта во ВКонтакте» — предлог зависит от названия. */
const PLATFORM_IN: Record<Network, string> = {
  telegram: "в Telegram", vk: "во ВКонтакте", max: "в MAX", rutube: "на Rutube",
};
export const PLATFORM_COLORS: Record<Network, string> = {
  telegram: "var(--platform-telegram)", vk: "var(--platform-vk)",
  max: "var(--platform-max)", rutube: "var(--platform-rutube)",
};
/** Уровни анализа: спокойный серый, затем тёплая шкала — как на карточке поста. */
export const LEVEL_NAMES = ["нет признаков", "слабый сигнал", "выраженная аномалия", "признаки искусственной активности"] as const;
export const LEVEL_COLORS = ["var(--muted-foreground)", "var(--chart-10)", "var(--chart-3)", "var(--destructive)"] as const;
/** Цвета выделенных вузов: различимые оттенки палитры графиков. */
export const HIGHLIGHT_COLORS = ["var(--chart-2)", "var(--chart-6)", "var(--chart-1)", "var(--chart-4)", "var(--chart-10)", "var(--chart-8)"] as const;
export const MAX_HIGHLIGHTS = HIGHLIGHT_COLORS.length;

/** Выделенные вузы: id → цвет, порядок — порядок выбора. */
export type HighlightMap = ReadonlyMap<string, string>;

export function highlightMap(ids: readonly string[]): HighlightMap {
  return new Map(ids.slice(0, MAX_HIGHLIGHTS).map((id, index) => [id, HIGHLIGHT_COLORS[index]!]));
}

/** Цвет закреплён за вузом, пока он выделен: снятие одного вуза не
 *  перекрашивает остальные, новый получает первый свободный цвет. */
export function toggleHighlight(current: HighlightMap, id: string): HighlightMap {
  const next = new Map(current);
  if (next.delete(id)) return next;
  if (next.size >= MAX_HIGHLIGHTS) return current;
  const used = new Set(next.values());
  next.set(id, HIGHLIGHT_COLORS.find((color) => !used.has(color))!);
  return next;
}

export const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"] as const;
/** Форматы — корзины API: редкие и платформенные коды уже сведены в «прочее». */
const TYPE_NAMES: Record<string, string> = {
  text: "Текст", photo: "Фото", album: "Альбом", video: "Видео", other: "Прочее",
};
export const typeName = (value: string) => TYPE_NAMES[value] ?? TYPE_NAMES.other!;

export function normalizeDashboardPlatform(value: string | undefined): DashboardPlatform {
  return DASHBOARD_PLATFORMS.includes(value as DashboardPlatform) ? value as DashboardPlatform : "all";
}
export function normalizeDashboardPeriod(value: string | undefined): DashboardPeriod {
  return value === "7d" ? "7d" : "30d";
}
export const periodDays = (period: DashboardPeriod) => (period === "7d" ? 7 : 30);

/** Строка вуза в выбранном разрезе площадок. */
export type InstitutionFinding = NonNullable<Dashboard["institutions"][number]["accountFindings"]>[number];

/** Названия аккаунтных находок — как на странице аккаунта. */
export const FINDING_TITLES: Record<InstitutionFinding["kind"], string> = {
  early_pack: "Повторяющийся стартовый пакет реакций",
  regular_reactions: "Слишком ровный отклик",
  late_growth: "Посты добирают реакции через дни",
  late_engagement: "Необычный отклик на старые посты",
  synchronous_waves: "Волны реакций сразу на многих постах",
  engagement_shift: "Отклик вырос без роста аудитории",
  night_reactions: "Реакции приходят ночью, когда просмотров нет",
};

export type InstitutionRow = {
  id: string; name: string; fullName: string;
  posts: number; postsPerDay: number; subscribers: number | null;
  subscriberNetworks: number; connectedNetworks: number;
  students: number | null; studentFact: components["schemas"]["InstitutionStudentCount"] | null;
  views24: number | null; reactions24: number | null; comments24: number | null; engagement24: number | null;
  viewsTotal: number; reactionsTotal: number; sample24: number;
  analyzed: number; levels: [number, number, number, number];
  /** Доля постов с уровнем 2–3 среди проанализированных, в процентах. */
  anomalyShare: number | null;
  /** Посты по площадкам — для профиля присутствия. */
  byNetwork: Record<Network, number>;
  /** Аккаунтные находки на выбранной площадке (на всех — в режиме «все»). */
  findings: InstitutionFinding[];
  /** Хотя бы одна устойчивая находка (статус 2) на выбранной площадке. */
  persistentFindings: boolean;
};

export type Metric =
  | "views24" | "reactions24" | "engagement24" | "postsPerDay" | "viewsTotal" | "subscribers" | "anomalyShare";

export const METRICS: Record<Metric, { label: string; short: string; unit?: string; percent?: boolean; hint: string }> = {
  views24: { label: "Просмотры поста за 24 часа, медиана", short: "Просмотры за 24 ч", hint: "Типичный пост: половина набирает за первые сутки больше, половина — меньше. Один возраст для всех, поэтому частые публикации не занижают число." },
  reactions24: { label: "Реакции поста за 24 часа, медиана", short: "Реакции за 24 ч", hint: "Реакции (в Telegram) и лайки (в остальных сетях) на 24-м часу после выхода, медиана по постам." },
  engagement24: { label: "Вовлечённость за 24 часа, медиана", short: "Вовлечённость", unit: "%", percent: true, hint: "Для каждого поста на 24-м часу: реакции / просмотры в Telegram, (лайки + комментарии + репосты) / просмотры в остальных. Медиана по постам." },
  postsPerDay: { label: "Публикаций в день", short: "Постов в день", hint: "Сколько публикаций в среднем выходило за сутки выбранного периода." },
  viewsTotal: { label: "Просмотры всех публикаций периода", short: "Просмотров всего", hint: "Сумма последних замеров просмотров всех публикаций, вышедших за период: общий охват." },
  subscribers: { label: "Подписчики", short: "Подписчики", hint: "Последний замер числа подписчиков официальных сообществ вуза." },
  anomalyShare: { label: "Доля постов с аномалиями", short: "Доля аномалий", unit: "%", percent: true, hint: "Доля постов с уровнем «выраженная аномалия» или «признаки искусственной активности» среди проанализированных. Сигнал аномальной динамики — информационный и сам по себе не доказывает накрутку." },
};

function statFor(data: Dashboard, institution: string | null, platform: DashboardPlatform) {
  return data.stats.find((stat) => stat.institutionId === institution && stat.platform === platform);
}

export function institutionRows(data: Dashboard, platform: DashboardPlatform): InstitutionRow[] {
  const days = periodDays(data.period as DashboardPeriod);
  const byKey = new Map<string, DashboardStat>();
  for (const stat of data.stats) if (stat.institutionId) byKey.set(`${stat.institutionId}|${stat.platform}`, stat);
  const rows: InstitutionRow[] = [];
  for (const institution of data.institutions) {
    const stat = byKey.get(`${institution.institutionId}|${platform}`);
    const networks: readonly Network[] = platform === "all" ? NETWORKS : [platform as Network];
    if (!networks.some((network) => institution.platforms.includes(network))) continue;
    const byNetwork = Object.fromEntries(NETWORKS.map((network) => [network, byKey.get(`${institution.institutionId}|${network}`)?.posts ?? 0])) as Record<Network, number>;
    const levels = (stat?.levels ?? [0, 0, 0, 0]) as [number, number, number, number];
    const analyzed = stat?.analyzed ?? 0;
    const findings = (institution.accountFindings ?? []).filter((item) => networks.includes(item.platform as Network));
    const availableSubscribers = networks.filter(network => institution.platforms.includes(network))
      .map(network => institution.subscribers[network]).filter((value): value is number => value !== null && value !== undefined);
    rows.push({
      id: institution.institutionId,
      name: institution.shortName || institution.name,
      fullName: institution.name,
      posts: stat?.posts ?? 0,
      postsPerDay: (stat?.posts ?? 0) / days,
      subscribers: availableSubscribers.length ? availableSubscribers.reduce((sum, value) => sum + value, 0) : null,
      subscriberNetworks: availableSubscribers.length,
      connectedNetworks: networks.filter(network => institution.platforms.includes(network)).length,
      students: institution.students?.value ?? null, studentFact: institution.students ?? null,
      views24: stat?.views24 ?? null, reactions24: stat?.reactions24 ?? null, comments24: stat?.comments24 ?? null,
      engagement24: stat?.engagement24 ?? null,
      viewsTotal: stat?.viewsTotal ?? 0, reactionsTotal: stat?.reactionsTotal ?? 0, sample24: stat?.sample24 ?? 0,
      analyzed, levels,
      anomalyShare: analyzed ? ((levels[2] + levels[3]) * 100) / analyzed : null,
      byNetwork,
      findings, persistentFindings: findings.some((item) => item.status === 2),
    });
  }
  return rows;
}

/** Вариант в поиске вуза: все вузы, а не только площадки вкладки, — с
 *  пометкой, почему вуза не будет на графиках. */
export type InstitutionOption = { id: string; name: string; fullName: string; note: string | null; weight: number };

export function institutionOptions(data: Dashboard, platform: DashboardPlatform): InstitutionOption[] {
  const networks: readonly Network[] = platform === "all" ? NETWORKS : [platform];
  return data.institutions.map((institution) => {
    const posts = statFor(data, institution.institutionId, platform)?.posts ?? 0;
    const note = !networks.some((network) => institution.platforms.includes(network))
      ? platform === "all" ? "нет аккаунтов в соцсетях" : `нет аккаунта ${PLATFORM_IN[platform]}`
      : posts ? null : "нет публикаций за период";
    return {
      id: institution.institutionId, name: institution.shortName || institution.name, fullName: institution.name,
      note, weight: statFor(data, institution.institutionId, "all")?.viewsTotal ?? 0,
    };
  });
}

/** Имена выделенных вузов не зависят от вкладки площадки. */
export function institutionLabels(data: Dashboard): ReadonlyMap<string, { name: string; fullName: string }> {
  return new Map(data.institutions.map((item) => [item.institutionId, { name: item.shortName || item.name, fullName: item.name }]));
}

export function metricValue(row: InstitutionRow, metric: Metric): number | null {
  return row[metric];
}

/** Сводка по площадке целиком: итоги и медианы по всем постам, а не медиана медиан. */
export function platformSummary(data: Dashboard, platform: DashboardPlatform, rows: readonly InstitutionRow[]) {
  const stat = statFor(data, null, platform);
  const analyzed = stat?.analyzed ?? 0;
  const levels = (stat?.levels ?? [0, 0, 0, 0]) as [number, number, number, number];
  return {
    institutions: rows.filter((row) => row.posts > 0).length,
    posts: stat?.posts ?? 0,
    postsPerDay: (stat?.posts ?? 0) / periodDays(data.period as DashboardPeriod),
    viewsTotal: stat?.viewsTotal ?? 0,
    reactionsTotal: stat?.reactionsTotal ?? 0,
    views24: stat?.views24 ?? null,
    reactions24: stat?.reactions24 ?? null,
    engagement24: stat?.engagement24 ?? null,
    analyzed, levels,
    anomalyShare: analyzed ? ((levels[2] + levels[3]) * 100) / analyzed : null,
  };
}

export function sortRows(rows: readonly InstitutionRow[], metric: Metric, descending = true): InstitutionRow[] {
  return [...rows].sort((left, right) => {
    const a = metricValue(left, metric), b = metricValue(right, metric);
    if (a === null && b === null) return left.name.localeCompare(right.name, "ru");
    if (a === null) return 1;
    if (b === null) return -1;
    return descending ? b - a : a - b;
  });
}

export function median(values: readonly number[]): number | null {
  const sorted = values.filter(Number.isFinite).toSorted((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle]! : (sorted[middle - 1]! + sorted[middle]!) / 2;
}

/** Процентильный ранг вуза по мере среди всех вузов разреза: 0 — худший,
 *  100 — лучший. Нужен радару: меры разного масштаба на одной шкале. */
export function percentileRank(rows: readonly InstitutionRow[], row: InstitutionRow, metric: Metric, inverse = false): number | null {
  const value = metricValue(row, metric);
  if (value === null) return null;
  const values = rows.map((item) => metricValue(item, metric)).filter((item): item is number => item !== null);
  if (values.length < 2) return 50;
  const below = values.filter((item) => (inverse ? item > value : item < value)).length;
  const equal = values.filter((item) => item === value).length - 1;
  return Math.round(((below + equal / 2) / (values.length - 1)) * 100);
}

/** Кривые накопления для графика: одна строка на час, столбец на вуз. Час —
 *  число: ось времени логарифмическая, промежутки между точками честные. */
export function curveRows(data: Dashboard, platform: Network, institutionIds: readonly string[], field: "views" | "reactions") {
  const curves = new Map(data.curves.filter((curve) => curve.platform === platform).map((curve) => [curve.institutionId ?? "median", curve]));
  return data.hours.map((hour, index) => {
    const point: Record<string, number | null> = { hour };
    point.median = curves.get("median")?.[field][index] ?? null;
    for (const id of institutionIds) point[id] = curves.get(id)?.[field][index] ?? null;
    return point;
  });
}

export function hourLabel(hour: number) {
  return hour < 24 ? `${hour} ч` : `${hour / 24} д`;
}

/** Московская дата среза: этот день ещё не закончился. */
export function moscowDay(at: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow" }).format(new Date(at));
}

/** Последний день окна, если это день среза: посты ещё выходят и набирают
 *  просмотры, поэтому его значение — не обрыв, а незаконченный день. */
export function incompleteDay(data: Dashboard): string | null {
  const day = moscowDay(data.asOf);
  return data.daily.some((row) => row.day === day) ? day : null;
}

/** Ряды по дням. Незаконченный день вынесен в ключи *_partial (вместе с
 *  предыдущим днём, чтобы нарисовать соединяющий пунктир), а в основных
 *  ключах он пуст: сплошная линия обрывается на последнем полном дне. */
export function dailyRows(data: Dashboard) {
  const days = [...new Set(data.daily.map((row) => row.day))].sort();
  const rows = days.map((day) => {
    const point: Record<string, number | string | null> = { day };
    for (const row of data.daily.filter((item) => item.day === day)) {
      point[`posts_${row.platform}`] = row.posts;
      point[`views_${row.platform}`] = row.viewsTotal ?? 0;
      point[`anomaly_${row.platform}`] = row.analyzed ? (row.anomalous * 100) / row.analyzed : null;
      point[`analyzed_${row.platform}`] = row.analyzed;
    }
    return point;
  });
  const last = rows.at(-1), previous = rows.at(-2);
  if (last && last.day === incompleteDay(data)) {
    for (const key of Object.keys(last)) {
      if (key === "day") continue;
      if (previous) previous[`${key}_partial`] = previous[key] ?? null;
      last[`${key}_partial`] = last[key] ?? null;
      last[key] = null;
    }
  }
  return rows;
}

/** Время и форматы: у панели — все вузы, у догрузки — один вуз. */
export type TimingSource = Pick<Dashboard, "timing" | "types">;

/** Сетка «день недели × час» для тепловой карты. */
export function timingGrid(data: TimingSource, platform: DashboardPlatform) {
  const grid = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => ({ posts: 0, views24: null as number | null })));
  for (const cell of data.timing) {
    if (cell.platform !== platform || cell.weekday === null) continue;
    grid[cell.weekday]![cell.hour] = { posts: cell.posts, views24: cell.views24 };
  }
  return grid;
}

/** Медиана просмотров за 24 часа по часу выхода — «когда публиковать».
 *  Строки без дня недели — медиана по всем постам этого часа. */
export function hourlyReach(data: TimingSource, platform: DashboardPlatform) {
  return Array.from({ length: 24 }, (_, hour) => {
    const cell = data.timing.find((item) => item.platform === platform && item.weekday === null && item.hour === hour);
    return { hour: `${String(hour).padStart(2, "0")}:00`, posts: cell?.posts ?? 0, views24: cell?.views24 ?? null };
  });
}

/** Форматы по убыванию числа постов, «Прочее» — последним; доля — от всех постов. */
export function typeRows(data: TimingSource, platform: DashboardPlatform) {
  const rows = data.types.filter((row) => row.platform === platform);
  const total = rows.reduce((sum, row) => sum + row.posts, 0);
  return rows
    .map((row) => ({ code: row.type, type: typeName(row.type), posts: row.posts, share: total ? (row.posts * 100) / total : 0,
      views24: row.views24, engagement24: row.engagement24 }))
    .sort((left, right) => Number(left.code === "other") - Number(right.code === "other") || right.posts - left.posts);
}

/** Уровни анализа по площадкам в процентах — для полосы «100 %». Для вуза —
 *  только площадки, где у него есть проанализированные посты. */
export function levelSharesByPlatform(data: Dashboard, institutionId: string | null = null) {
  return NETWORKS.flatMap((network) => {
    const stat = statFor(data, institutionId, network);
    const analyzed = stat?.analyzed ?? 0;
    if (institutionId && !analyzed) return [];
    const point: Record<string, number | string> = { platform: PLATFORM_NAMES[network], analyzed };
    (stat?.levels ?? [0, 0, 0, 0]).forEach((count, level) => { point[`level${level}`] = analyzed ? (count * 100) / analyzed : 0; });
    return [point];
  });
}

/** Уровни анализа вуза на вкладке площадки. */
export function institutionLevels(data: Dashboard, institutionId: string, platform: DashboardPlatform) {
  const stat = statFor(data, institutionId, platform);
  return { analyzed: stat?.analyzed ?? 0, levels: (stat?.levels ?? [0, 0, 0, 0]) as [number, number, number, number] };
}

/** Чей разрез показывает карточка: «auto» — последний выделенный вуз (так
 *  карточка сама переходит к только что выбранному), «all» — все вузы, иначе
 *  выбранный в карточке вуз, пока он выделен. */
export type Scope = "auto" | "all" | (string & {});
export function resolveScope(scope: Scope, highlightIds: readonly string[]): string {
  if (scope === "all") return "all";
  if (scope !== "auto" && highlightIds.includes(scope)) return scope;
  return highlightIds.at(-1) ?? "all";
}

const integer = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const compact = new Intl.NumberFormat("ru-RU", { notation: "compact", maximumFractionDigits: 1 });

export function formatValue(value: number | null | undefined, metric?: Metric): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (metric && METRICS[metric].percent) return `${decimal.format(value)}%`;
  if (metric === "postsPerDay") return decimal.format(value);
  return Math.abs(value) >= 100_000 ? compact.format(value) : integer.format(value);
}
export const formatInteger = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : integer.format(value);
export const formatCompact = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : Math.abs(value) >= 10_000 ? compact.format(value) : integer.format(value);
export const formatPercent = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${decimal.format(value)}%`;

/** Переключатель «Скрыть вузы с устойчивыми находками». */
export function withoutPersistentFindings<T extends Pick<InstitutionRow, "persistentFindings">>(rows: readonly T[]): T[] {
  return rows.filter((row) => !row.persistentFindings);
}

/** Подсказка к значку находок: вид, площадка в режиме «все», устойчивость; null — находок нет. */
export function findingsNote(row: Pick<InstitutionRow, "findings">): string | null {
  if (!row.findings.length) return null;
  const platforms = new Set(row.findings.map((item) => item.platform));
  return "Находки аккаунтов: " + row.findings.map((item) => `${FINDING_TITLES[item.kind]}`
    + (platforms.size > 1 ? ` — ${PLATFORM_NAMES[item.platform as Network]}` : "")
    + (item.status === 2 ? " (устойчиво)" : "")).join("; ");
}
