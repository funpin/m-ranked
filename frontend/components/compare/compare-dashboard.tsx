"use client";

import dynamic from "next/dynamic";
import { useCallback, useDeferredValue, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity, ArrowDownUp, CalendarClock, ChartBar, ChartNetwork, ChartScatter, Clock, Eye, Heart, LayoutGrid, Newspaper,
  Search, ShieldAlert, Sparkles, Table2, TrendingUp, University, X,
} from "lucide-react";
import Link from "@/components/native-link";
import { Badge } from "@/components/ui/badge";
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { MethodNote } from "@/components/method-note";
import { cn } from "@/lib/utils";
import {
  DASHBOARD_PLATFORMS, HIGHLIGHT_COLORS, LEVEL_COLORS, LEVEL_NAMES, MAX_HIGHLIGHTS, METRICS, NETWORKS, PLATFORM_NAMES,
  WEEKDAYS, formatCompact, formatInteger, formatPercent, formatValue, institutionRows, platformSummary, sortRows,
  timingGrid, type Dashboard, type DashboardPeriod, type DashboardPlatform, type InstitutionRow, type Metric, type Network,
} from "@/lib/compare-dashboard";

function ChartSkeleton({ height = 300 }: { height?: number }) {
  return <Skeleton className="w-full rounded-lg" style={{ height }} aria-label="График загружается" role="status" />;
}
// Графики — отдельный фрагмент кода: оболочка страницы, сводка и таблица
// приходят с сервера сразу, библиотека графиков догружается следом.
const load = <K extends keyof typeof import("./compare-charts")>(name: K, height = 300) =>
  dynamic(() => import("./compare-charts").then((module) => module[name] as never), {
    ssr: false, loading: () => <ChartSkeleton height={height} />,
  });
const RankingChart = load("RankingChart", 480) as typeof import("./compare-charts").RankingChart;
const ScatterMap = load("ScatterMap", 360) as typeof import("./compare-charts").ScatterMap;
const CurvesChart = load("CurvesChart", 340) as typeof import("./compare-charts").CurvesChart;
const LevelsDonut = load("LevelsDonut", 240) as typeof import("./compare-charts").LevelsDonut;
const LevelsByPlatform = load("LevelsByPlatform", 240) as typeof import("./compare-charts").LevelsByPlatform;
const DailyChart = load("DailyChart") as typeof import("./compare-charts").DailyChart;
const ReachAreaChart = load("ReachAreaChart") as typeof import("./compare-charts").ReachAreaChart;
const HourlyReachChart = load("HourlyReachChart", 280) as typeof import("./compare-charts").HourlyReachChart;
const TypesChart = load("TypesChart", 240) as typeof import("./compare-charts").TypesChart;
const RadarProfile = load("RadarProfile", 360) as typeof import("./compare-charts").RadarProfile;
const PresenceChart = load("PresenceChart", 600) as typeof import("./compare-charts").PresenceChart;

const RANKING_METRICS: Metric[] = ["views24", "reactions24", "engagement24", "postsPerDay", "viewsTotal", "subscribers"];
const SCATTER_PRESETS: { id: string; label: string; x: Metric; y: Metric }[] = [
  { id: "reach", label: "Активность и охват", x: "postsPerDay", y: "views24" },
  { id: "engagement", label: "Охват и вовлечённость", x: "views24", y: "engagement24" },
  { id: "audience", label: "Аудитория и охват", x: "subscribers", y: "views24" },
];
const SECTIONS = [
  { id: "summary", label: "Сводка", icon: LayoutGrid },
  { id: "ranking", label: "Рейтинг", icon: ChartBar },
  { id: "map", label: "Карта вузов", icon: ChartScatter },
  { id: "growth", label: "Накопление", icon: TrendingUp },
  { id: "anomalies", label: "Аномалии", icon: ShieldAlert },
  { id: "dynamics", label: "Динамика", icon: Activity },
  { id: "timing", label: "Время и форматы", icon: Clock },
  { id: "table", label: "Таблица", icon: Table2 },
] as const;

function Section({ id, title, description, icon: Icon, children }: {
  id: string; title: string; description?: string; icon: typeof ChartBar; children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="min-w-0 scroll-mt-28">
      <div className="mb-3 flex items-center gap-2">
        <span className="bg-primary/10 text-primary flex size-7 items-center justify-center rounded-md"><Icon className="size-4" aria-hidden="true" /></span>
        <div>
          <h2 id={`${id}-title`} className="font-heading text-lg leading-tight font-semibold">{title}</h2>
          {description ? <p className="text-muted-foreground text-sm">{description}</p> : null}
        </div>
      </div>
      {children}
    </section>
  );
}

function Kpi({ icon: Icon, label, value, hint, note, tone }: {
  icon: typeof Eye; label: string; value: string; hint?: string; note?: string; tone?: "danger";
}) {
  return (
    <Card className="gap-2 py-4" data-testid="compare-kpi">
      <CardHeader className="px-4">
        <CardDescription className="flex items-center gap-1.5">
          <Icon className="size-3.5" aria-hidden="true" />{label}
          {note ? <MethodNote title={label}>{note}</MethodNote> : null}
        </CardDescription>
        <CardTitle className={cn("font-heading text-2xl font-bold tabular-nums", tone === "danger" && "text-destructive")}>{value}</CardTitle>
      </CardHeader>
      {hint ? <CardFooter className="text-muted-foreground px-4 text-xs">{hint}</CardFooter> : null}
    </Card>
  );
}

function ChartCard({ title, description, note, action, footer, children, className, testId }: {
  title: string; description?: string; note?: string; action?: ReactNode; footer?: ReactNode;
  children: ReactNode; className?: string; testId?: string;
}) {
  return (
    <Card className={cn("min-w-0", className)} data-testid={testId}>
      <CardHeader>
        <CardTitle as="h3" className="flex items-center gap-1 text-base">{title}{note ? <MethodNote title={title}>{note}</MethodNote> : null}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
        {action ? <CardAction>{action}</CardAction> : null}
      </CardHeader>
      <CardContent className="min-w-0">{children}</CardContent>
      {footer ? <CardFooter className="text-muted-foreground text-xs">{footer}</CardFooter> : null}
    </Card>
  );
}

function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: readonly { value: T; label: string }[]; onChange: (value: T) => void; label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="bg-muted text-muted-foreground inline-flex flex-wrap rounded-lg p-[3px]">
      {options.map((option) => (
        <button key={option.value} type="button" role="radio" aria-checked={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn("rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none",
            value === option.value ? "bg-background text-foreground shadow-sm" : "hover:text-foreground")}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** Выбор выделенных вузов: поиск по названию, до шести цветных меток. Все
 *  вузы остаются на графиках — выделение только подсвечивает. */
function HighlightPicker({ rows, highlights, onToggle, onClear }: {
  rows: readonly InstitutionRow[]; highlights: ReadonlyMap<string, string>;
  onToggle: (id: string) => void; onClear: () => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const deferred = useDeferredValue(query);
  const matches = useMemo(() => {
    const needle = deferred.trim().toLocaleLowerCase("ru");
    return rows.filter((row) => !highlights.has(row.id)
      && (!needle || row.name.toLocaleLowerCase("ru").includes(needle) || row.fullName.toLocaleLowerCase("ru").includes(needle)))
      .slice(0, 8);
  }, [rows, highlights, deferred]);
  const names = new Map(rows.map((row) => [row.id, row.name]));
  const full = highlights.size >= MAX_HIGHLIGHTS;
  return (
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
      <div className="relative w-full sm:w-64">
        <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden="true" />
        <Input value={query} disabled={full} placeholder={full ? `Выделено ${MAX_HIGHLIGHTS} из ${MAX_HIGHLIGHTS}` : "Выделить вуз на графиках…"}
          aria-label="Найти вуз для выделения" className="pl-8" data-testid="highlight-search"
          onChange={(event) => { setQuery(event.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && matches[0]) { event.preventDefault(); onToggle(matches[0].id); setQuery(""); }
            if (event.key === "Escape") setOpen(false);
          }} />
        {open && !full && matches.length ? (
          <ul role="listbox" aria-label="Вузы" className="bg-popover text-popover-foreground ring-foreground/10 absolute z-30 mt-1 max-h-72 w-full overflow-auto rounded-lg p-1 text-sm shadow-md ring-1">
            {matches.map((row) => (
              <li key={row.id} role="option" aria-selected={false}>
                <button type="button" className="hover:bg-accent w-full rounded-md px-2 py-1.5 text-left"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => { onToggle(row.id); setQuery(""); }}>
                  <span className="font-medium">{row.name}</span>
                  {row.fullName !== row.name ? <span className="text-muted-foreground block truncate text-xs">{row.fullName}</span> : null}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {[...highlights].map(([id, color]) => (
        <Badge key={id} variant="outline" className="gap-1.5 rounded-full py-1 pr-1 pl-2" data-testid="highlight-chip">
          <span className="size-2.5 rounded-full" style={{ background: color }} aria-hidden="true" />
          {names.get(id) ?? "вуз"}
          <button type="button" onClick={() => onToggle(id)} aria-label={`Снять выделение: ${names.get(id) ?? "вуз"}`}
            className="hover:bg-muted rounded-full p-0.5"><X className="size-3" /></button>
        </Badge>
      ))}
      {highlights.size ? <button type="button" onClick={onClear} className="text-muted-foreground hover:text-foreground text-xs underline underline-offset-4">Сбросить</button> : null}
    </div>
  );
}

/** Тепловая карта «день недели × час выхода»: число публикаций, в подсказке —
 *  медиана просмотров за сутки. Сетка из блоков, без графической библиотеки. */
function TimingHeatmap({ data, platform }: { data: Dashboard; platform: DashboardPlatform }) {
  const grid = useMemo(() => timingGrid(data, platform), [data, platform]);
  const peak = Math.max(1, ...grid.flat().map((cell) => cell.posts));
  return (
    // На узком экране сетка прокручивается: область фокусируется с клавиатуры.
    <div className="overflow-x-auto focus-visible:ring-ring/50 rounded-md focus-visible:ring-[3px] focus-visible:outline-none"
      data-testid="timing-heatmap" tabIndex={0} role="region" aria-label="Публикации по дню недели и часу выхода">
      <div className="grid min-w-[560px] gap-[3px]" style={{ gridTemplateColumns: "28px repeat(24, minmax(0, 1fr))" }} role="table" aria-label="Публикации по дню недели и часу">
        <span />
        {Array.from({ length: 24 }, (_, hour) => (
          <span key={hour} className="text-muted-foreground text-center text-[10px]">{hour % 3 === 0 ? hour : ""}</span>
        ))}
        {grid.map((row, weekday) => (
          <div key={weekday} className="contents" role="row">
            <span className="text-muted-foreground self-center text-[11px]" role="rowheader">{WEEKDAYS[weekday]}</span>
            {row.map((cell, hour) => {
              const intensity = cell.posts / peak;
              return (
                <span key={hour} role="cell"
                  title={`${WEEKDAYS[weekday]}, ${String(hour).padStart(2, "0")}:00 — ${formatInteger(cell.posts)} публ., медиана просмотров за 24 ч: ${formatInteger(cell.views24)}`}
                  className="aspect-square rounded-[3px]"
                  style={{ background: cell.posts ? `color-mix(in oklch, var(--chart-2) ${Math.round(12 + intensity * 88)}%, transparent)` : "var(--muted)" }} />
              );
            })}
          </div>
        ))}
      </div>
      <div className="text-muted-foreground mt-2 flex items-center gap-2 text-[11px]">
        меньше
        {[0.12, 0.35, 0.6, 0.85, 1].map((step) => (
          <span key={step} className="size-3 rounded-[3px]" style={{ background: `color-mix(in oklch, var(--chart-2) ${Math.round(step * 100)}%, transparent)` }} />
        ))}
        больше публикаций
      </div>
    </div>
  );
}

/** Полоса уровней анализа в строке таблицы: доли 0–3 одной строкой. */
function LevelBar({ levels }: { levels: readonly number[] }) {
  const total = levels.reduce((sum, value) => sum + value, 0);
  if (!total) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="bg-muted flex h-2 w-24 overflow-hidden rounded-full" role="img"
      aria-label={levels.map((count, level) => `${LEVEL_NAMES[level]}: ${count}`).join(", ")}
      title={levels.map((count, level) => `${LEVEL_NAMES[level]}: ${count}`).join("\n")}>
      {levels.map((count, level) => count ? <span key={level} style={{ width: `${(count * 100) / total}%`, background: LEVEL_COLORS[level] }} /> : null)}
    </span>
  );
}

type SortKey = "name" | "posts" | Metric | "analyzed";
const TABLE_COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: "name", label: "Вуз" },
  { key: "posts", label: "Публикаций", numeric: true },
  { key: "postsPerDay", label: "В день", numeric: true },
  { key: "subscribers", label: "Подписчики", numeric: true },
  { key: "views24", label: "Просмотры 24 ч", numeric: true },
  { key: "reactions24", label: "Реакции 24 ч", numeric: true },
  { key: "engagement24", label: "Вовлечённость", numeric: true },
  { key: "viewsTotal", label: "Просмотров всего", numeric: true },
  { key: "analyzed", label: "Проанализировано", numeric: true },
  { key: "anomalyShare", label: "Аномалии", numeric: true },
];

function InstitutionTable({ rows, highlights, onToggle }: {
  rows: readonly InstitutionRow[]; highlights: ReadonlyMap<string, string>; onToggle: (id: string) => void;
}) {
  const [sort, setSort] = useState<{ key: SortKey; descending: boolean }>({ key: "views24", descending: true });
  const sorted = useMemo(() => {
    if (sort.key === "name") return [...rows].sort((a, b) => (sort.descending ? -1 : 1) * a.name.localeCompare(b.name, "ru"));
    if (sort.key === "posts" || sort.key === "analyzed") {
      const key = sort.key;
      return [...rows].sort((a, b) => (sort.descending ? b[key] - a[key] : a[key] - b[key]));
    }
    return sortRows(rows, sort.key, sort.descending);
  }, [rows, sort]);
  return (
    <div className="overflow-x-auto" data-testid="compare-table">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10">#</TableHead>
            {TABLE_COLUMNS.map((column) => (
              <TableHead key={column.key} className={cn(column.numeric && "text-right")}
                aria-sort={sort.key === column.key ? (sort.descending ? "descending" : "ascending") : "none"}>
                <button type="button" className="hover:text-foreground inline-flex items-center gap-1 font-medium"
                  onClick={() => setSort((current) => ({ key: column.key, descending: current.key === column.key ? !current.descending : column.key !== "name" }))}>
                  {column.label}<ArrowDownUp className={cn("size-3", sort.key === column.key ? "opacity-100" : "opacity-30")} aria-hidden="true" />
                </button>
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((row, index) => {
            const color = highlights.get(row.id);
            return (
              <TableRow key={row.id} data-highlighted={color ? "true" : undefined} className={cn(color && "bg-muted/60")}>
                <TableCell className="text-muted-foreground tabular-nums">{index + 1}</TableCell>
                <TableCell className="max-w-[260px]">
                  <button type="button" onClick={() => onToggle(row.id)} className="flex items-center gap-2 text-left"
                    title={color ? "Снять выделение" : "Выделить на графиках"}>
                    <span className="size-2.5 shrink-0 rounded-full border" style={{ background: color ?? "transparent" }} aria-hidden="true" />
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{row.name}</span>
                      {row.fullName !== row.name ? <span className="text-muted-foreground block truncate text-xs">{row.fullName}</span> : null}
                    </span>
                  </button>
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatInteger(row.posts)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatValue(row.postsPerDay, "postsPerDay")}</TableCell>
                <TableCell className="text-right tabular-nums">{formatCompact(row.subscribers || null)}</TableCell>
                <TableCell className="text-right font-medium tabular-nums">{formatInteger(row.views24)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatInteger(row.reactions24)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatPercent(row.engagement24)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatCompact(row.viewsTotal || null)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatInteger(row.analyzed)}</TableCell>
                <TableCell className="text-right">
                  <span className="inline-flex items-center justify-end gap-2">
                    <LevelBar levels={row.levels} />
                    <span className={cn("w-12 tabular-nums", (row.anomalyShare ?? 0) >= 10 && "text-destructive font-medium")}>{formatPercent(row.anomalyShare)}</span>
                  </span>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

const SHORT_PLATFORM_NAMES: Partial<Record<DashboardPlatform, string>> = { all: "Все", vk: "ВК" };

export function CompareDashboard({ data, period, initialPlatform, initialHighlights }: {
  data: Dashboard; period: DashboardPeriod; initialPlatform: DashboardPlatform; initialHighlights: readonly string[];
}) {
  const [platform, setPlatform] = useState(initialPlatform);
  const [rankingMetric, setRankingMetric] = useState<Metric>("views24");
  const [scatter, setScatter] = useState(SCATTER_PRESETS[0]!.id);
  const [curveField, setCurveField] = useState<"views" | "reactions">("views");
  const [curveNetwork, setCurveNetwork] = useState<Network>(initialPlatform === "all" ? "telegram" : initialPlatform);
  const [highlightIds, setHighlightIds] = useState<string[]>(() =>
    initialHighlights.filter((id) => data.institutions.some((item) => item.institutionId === id)).slice(0, MAX_HIGHLIGHTS));

  const rows = useMemo(() => institutionRows(data, platform), [data, platform]);
  const activeRows = useMemo(() => rows.filter((row) => row.posts > 0), [rows]);
  const summary = useMemo(() => platformSummary(data, platform, rows), [data, platform, rows]);
  const highlights = useMemo(() => new Map(highlightIds.map((id, index) => [id, HIGHLIGHT_COLORS[index]!])), [highlightIds]);
  // Без выделения радару нужны примеры: три вуза с наибольшим охватом поста.
  const radarHighlights = useMemo(() => highlights.size ? highlights
    : new Map(sortRows(activeRows, "views24").slice(0, 3).map((row, index) => [row.id, HIGHLIGHT_COLORS[index]!])), [highlights, activeRows]);
  const curveRowsForNetwork = useMemo(() => institutionRows(data, curveNetwork).filter((row) => row.posts > 0), [data, curveNetwork]);
  const anomalyRows = useMemo(() => activeRows.filter((row) => row.analyzed >= 5), [activeRows]);

  // Площадка и выделение — в адресе: ссылкой можно поделиться, а смена
  // вкладки не перезагружает страницу и не ходит на сервер.
  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("platform", platform);
    if (highlightIds.length) url.searchParams.set("highlight", highlightIds.join(","));
    else url.searchParams.delete("highlight");
    window.history.replaceState(window.history.state, "", url);
  }, [platform, highlightIds]);

  const toggle = useCallback((id: string) => setHighlightIds((current) =>
    current.includes(id) ? current.filter((item) => item !== id)
      : current.length >= MAX_HIGHLIGHTS ? current : [...current, id]), []);
  const changePlatform = (value: DashboardPlatform) => {
    setPlatform(value);
    if (value !== "all") setCurveNetwork(value);
  };

  const preset = SCATTER_PRESETS.find((item) => item.id === scatter) ?? SCATTER_PRESETS[0]!;
  const days = period === "7d" ? 7 : 30;
  const periodHref = (value: DashboardPeriod) => {
    const params = new URLSearchParams({ period: value, platform });
    if (highlightIds.length) params.set("highlight", highlightIds.join(","));
    return `/compare?${params}`;
  };

  return (
    // min-w-0: секции — элементы сетки, и без него широкая таблица вузов
    // растягивала колонку, а с ней всю страницу за край окна.
    <div className="grid min-w-0 grid-cols-1 gap-8" data-testid="compare-dashboard">
      <div className="bg-background/85 supports-[backdrop-filter]:bg-background/70 sticky top-14 z-20 -mx-4 border-b px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-xl sm:border">
        <div className="flex flex-wrap items-center gap-3">
          {/* Лёгкий список вкладок вместо компонента Tabs: переключение не
              меняет панель под ним, а меняет разрез данных, и библиотечная
              машинерия панелей здесь была бы лишним весом первой загрузки. */}
          <div role="tablist" aria-label="Соцсеть" data-testid="platform-tabs"
            className="bg-muted text-muted-foreground grid h-8 w-full grid-cols-4 items-center rounded-lg p-[3px] sm:inline-flex sm:w-auto"
            onKeyDown={(event) => {
              if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
              const index = DASHBOARD_PLATFORMS.indexOf(platform);
              const next = DASHBOARD_PLATFORMS[(index + (event.key === "ArrowRight" ? 1 : -1) + DASHBOARD_PLATFORMS.length) % DASHBOARD_PLATFORMS.length]!;
              changePlatform(next);
              (event.currentTarget.querySelector(`[data-value="${next}"]`) as HTMLElement | null)?.focus();
            }}>
            {DASHBOARD_PLATFORMS.map((value) => (
              <button key={value} type="button" role="tab" data-value={value} aria-selected={platform === value}
                tabIndex={platform === value ? 0 : -1} onClick={() => changePlatform(value)}
                className={cn("rounded-md px-2 py-0.5 text-sm font-medium whitespace-nowrap transition-colors focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none",
                  platform === value ? "bg-background text-foreground shadow-sm" : "hover:text-foreground")}>
                {/* На телефоне четыре полных названия не помещаются в строку. */}
                {SHORT_PLATFORM_NAMES[value]
                  ? <><span className="sm:hidden">{SHORT_PLATFORM_NAMES[value]}</span><span className="max-sm:hidden">{PLATFORM_NAMES[value]}</span></>
                  : PLATFORM_NAMES[value]}
              </button>
            ))}
          </div>
          <nav aria-label="Период" className="bg-muted text-muted-foreground inline-flex h-8 items-center rounded-lg p-[3px]">
            {(["7d", "30d"] as const).map((value) => (
              <Link key={value} href={periodHref(value)} prefetch={false} aria-current={period === value ? "page" : undefined}
                className={cn("rounded-md px-2 py-0.5 text-sm font-medium", period === value ? "bg-background text-foreground shadow-sm" : "hover:text-foreground")}>
                {value === "7d" ? "7 дней" : "30 дней"}
              </Link>
            ))}
          </nav>
          <HighlightPicker rows={rows} highlights={highlights} onToggle={toggle} onClear={() => setHighlightIds([])} />
        </div>
        <nav aria-label="Разделы страницы" className="mt-2 hidden flex-wrap gap-1 md:flex">
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <a key={id} href={`#${id}`} className="text-muted-foreground hover:bg-muted hover:text-foreground inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs">
              <Icon className="size-3.5" aria-hidden="true" />{label}
            </a>
          ))}
        </nav>
      </div>

      <Section id="summary" title={`${PLATFORM_NAMES[platform]} · ${days} дней`} icon={LayoutGrid}
        description="Итоги по всем вузам сразу. Медианы — по всем публикациям площадки, а не медиана медиан вузов.">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <Kpi icon={University} label="Вузов с публикациями" value={formatInteger(summary.institutions)} hint={`из ${rows.length} с аккаунтами`} />
          <Kpi icon={Newspaper} label="Публикаций" value={formatInteger(summary.posts)} hint={`≈ ${formatValue(summary.postsPerDay, "postsPerDay")} в день`} />
          <Kpi icon={Eye} label="Просмотров всего" value={formatCompact(summary.viewsTotal)} note={METRICS.viewsTotal.hint} />
          <Kpi icon={Sparkles} label="Типичный пост за 24 ч" value={formatInteger(summary.views24)} hint="просмотров, медиана" note={METRICS.views24.hint} />
          <Kpi icon={Heart} label="Вовлечённость" value={formatPercent(summary.engagement24)} hint="медиана на 24-м часу" note={METRICS.engagement24.hint} />
          <Kpi icon={ShieldAlert} label="Посты с аномалиями" value={formatPercent(summary.anomalyShare)} tone={(summary.anomalyShare ?? 0) >= 10 ? "danger" : undefined}
            hint={`${formatInteger(summary.levels[2] + summary.levels[3])} из ${formatInteger(summary.analyzed)} проанализированных`} note={METRICS.anomalyShare.hint} />
        </div>
      </Section>

      <Section id="ranking" title="Рейтинг вузов" icon={ChartBar} description={`Все ${activeRows.length} вузов на одной шкале, без ограничения по числу.`}>
        <ChartCard title={METRICS[rankingMetric].label} note={METRICS[rankingMetric].hint} testId="ranking-card"
          action={<select value={rankingMetric} onChange={(event) => setRankingMetric(event.target.value as Metric)} aria-label="Мера рейтинга"
            className="border-input bg-transparent dark:bg-input/30 h-8 rounded-md border px-2 text-sm shadow-xs focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none">
            {RANKING_METRICS.map((metric) => <option key={metric} value={metric}>{METRICS[metric].short}</option>)}
          </select>}
          footer="Пунктир — медиана по вузам. Выделенные вузы подсвечены цветом, остальные приглушены.">
          <RankingChart rows={activeRows} metric={rankingMetric} highlights={highlights} />
        </ChartCard>
      </Section>

      <Section id="map" title="Карта вузов" icon={ChartScatter} description="Две меры сразу: где вуз относительно остальных. Размер точки — число подписчиков.">
        <div className="grid gap-4 xl:grid-cols-5">
          <ChartCard className="xl:col-span-3" title={preset.label} testId="scatter-card"
            note="Обе оси логарифмические: вузы различаются на порядки. Пунктиры — медианы, они делят карту на четыре квадранта."
            action={<Segmented label="Пара мер" value={scatter} onChange={setScatter} options={SCATTER_PRESETS.map((item) => ({ value: item.id, label: item.label }))} />}>
            <ScatterMap rows={activeRows} x={preset.x} y={preset.y} highlights={highlights} />
          </ChartCard>
          <ChartCard className="xl:col-span-2" title="Профиль вуза" testId="radar-card"
            description={highlights.size ? "Выделенные вузы" : "Три вуза с наибольшим охватом поста — выделите свои"}
            note="Место вуза среди всех вузов по шести мерам: 100 — лучший, 0 — последний. «Чистота динамики» — обратная доля постов с аномалиями.">
            <RadarProfile rows={activeRows} highlights={radarHighlights} />
          </ChartCard>
        </div>
      </Section>

      <Section id="growth" title="Как набираются просмотры" icon={TrendingUp}
        description="Медиана значения поста на фиксированных часах после выхода — от первого часа до недели.">
        <ChartCard title={`${curveField === "views" ? "Просмотры" : "Реакции"} по возрасту поста · ${PLATFORM_NAMES[curveNetwork]}`} testId="curves-card"
          note="Площадки не смешиваются: просмотр в Telegram и во ВКонтакте значит разное. Тонкие линии — все вузы площадки, жирная — медиана площадки."
          action={<div className="flex flex-wrap gap-2">
            {platform === "all" ? <Segmented label="Площадка кривых" value={curveNetwork} onChange={setCurveNetwork}
              options={NETWORKS.map((network) => ({ value: network, label: PLATFORM_NAMES[network] }))} /> : null}
            <Segmented label="Мера кривых" value={curveField} onChange={setCurveField}
              options={[{ value: "views", label: "Просмотры" }, { value: "reactions", label: "Реакции" }]} />
          </div>}>
          <CurvesChart data={data} platform={curveNetwork} rows={curveRowsForNetwork} highlights={highlights} field={curveField} />
        </ChartCard>
      </Section>

      <Section id="anomalies" title="Аномальная динамика" icon={ShieldAlert}
        description="Выводы модуля анализа по постам периода. Сигнал информационный и сам по себе не доказывает накрутку.">
        <div className="grid gap-4 lg:grid-cols-3">
          <ChartCard title="Уровни анализа" description={`${formatInteger(summary.analyzed)} проанализированных постов`} testId="levels-card"
            note="Уровень складывается из согласия независимых семейств методов. «С аномалиями» — уровни «выраженная аномалия» и «признаки искусственной активности».">
            <LevelsDonut levels={summary.levels} />
            <ul className="mt-3 grid gap-1 text-xs">
              {LEVEL_NAMES.map((name, level) => (
                <li key={name} className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: LEVEL_COLORS[level] }} />{name}</span>
                  <span className="text-muted-foreground tabular-nums">{formatInteger(summary.levels[level])}</span>
                </li>
              ))}
            </ul>
          </ChartCard>
          <ChartCard className="lg:col-span-2" title="Уровни по соцсетям" description="Каждая полоса — все проанализированные посты площадки"
            testId="levels-platform-card">
            <LevelsByPlatform data={data} />
          </ChartCard>
        </div>
        <div className="mt-4">
          <ChartCard title="Доля постов с аномалиями по вузам" testId="anomaly-ranking-card"
            description={`${anomalyRows.length} вузов, у которых проанализировано хотя бы 5 постов`}
            note={METRICS.anomalyShare.hint}>
            <RankingChart rows={anomalyRows} metric="anomalyShare" highlights={highlights} />
          </ChartCard>
        </div>
      </Section>

      <Section id="dynamics" title="Динамика по дням" icon={Activity} description="По московской дате выхода публикации.">
        <div className="grid gap-4 xl:grid-cols-2">
          <ChartCard title="Публикации и доля аномалий" testId="daily-card"
            note="Области — число публикаций по площадкам; линия — доля постов с уровнем 2–3 среди проанализированных за день.">
            <DailyChart data={data} platform={platform} />
          </ChartCard>
          <ChartCard title="Охват по дню выхода" testId="reach-card"
            note="Сумма последних замеров просмотров постов, вышедших в этот день. Свежие дни ещё добирают просмотры.">
            <ReachAreaChart data={data} platform={platform} />
          </ChartCard>
        </div>
        {platform === "all" ? (
          <div className="mt-4">
            <ChartCard title="Присутствие в соцсетях" testId="presence-card" description="Публикации каждого вуза по площадкам за период">
              <PresenceChart rows={activeRows} highlights={highlights} />
            </ChartCard>
          </div>
        ) : null}
      </Section>

      <Section id="timing" title="Время и форматы" icon={CalendarClock} description="Когда вузы публикуют и что работает лучше.">
        <div className="grid gap-4 xl:grid-cols-2">
          <ChartCard title="Когда публикуют" description="День недели и час выхода, московское время" testId="heatmap-card">
            <TimingHeatmap data={data} platform={platform} />
          </ChartCard>
          <ChartCard title="Час выхода и охват" testId="hourly-card"
            note="Столбцы — сколько постов вышло в этот час; линия — медиана просмотров за первые сутки у постов этого часа.">
            <HourlyReachChart data={data} platform={platform} />
          </ChartCard>
        </div>
        <div className="mt-4">
          <ChartCard title="Форматы публикаций" testId="types-card" description="Сколько публикаций каждого формата и медиана их просмотров за 24 часа">
            <TypesChart data={data} platform={platform} />
          </ChartCard>
        </div>
      </Section>

      <Section id="table" title="Все вузы" icon={ChartNetwork} description="Сортировка — по клику на заголовок, выделение — по клику на вуз.">
        <Card className="py-2"><CardContent className="px-2"><InstitutionTable rows={rows} highlights={highlights} onToggle={toggle} /></CardContent></Card>
      </Section>
    </div>
  );
}
