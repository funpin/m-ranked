"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Activity, ArrowDownUp, CalendarClock, ChartBar, ChartNetwork, ChartScatter, Clock, Eye, Heart, LayoutGrid, Newspaper,
  ShieldAlert, Sparkles, Table2, TrendingUp, University,
} from "lucide-react";
import Link from "@/components/native-link";
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button"
import { buttonVariants } from "@/components/ui/button-variants";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useStuck } from "@/components/use-stuck";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { MethodNote } from "@/components/method-note";
import { TimingHeatmap } from "./timing-heatmap";
import { HighlightBar } from "./highlight-bar";
import { useInstitutionTiming } from "./use-institution-timing";
import { cn } from "@/lib/utils";
import { OVERLAY_MIN_POSTS } from "@/lib/compare-timing";
import { STICKY_CONTROL_SURFACE_CLASS } from "@/components/filter-toolbar";
import {
  DASHBOARD_PLATFORMS, LEVEL_COLORS, LEVEL_NAMES, MAX_HIGHLIGHTS, METRICS, NETWORKS, PLATFORM_NAMES,
  formatCompact, formatInteger, formatPercent, formatValue, highlightMap, institutionLabels, institutionOptions,
  institutionRows, platformSummary, sortRows, timingGrid, toggleHighlight,
  type Dashboard, type DashboardPeriod, type DashboardPlatform, type HighlightMap, type InstitutionRow, type Metric,
  type Network,
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
  { id: "ranking", label: "По показателю", icon: ChartBar },
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
    <section id={id} aria-labelledby={`${id}-title`} className="min-w-0 scroll-mt-48">
      {/* Иконка — в строке заголовка: описание в несколько строк её не сдвигает. */}
      <div className="mb-3 grid grid-cols-[1.75rem_minmax(0,1fr)] items-center gap-x-2">
        <span className="bg-primary/10 text-primary flex size-7 items-center justify-center rounded-md"><Icon className="size-4" aria-hidden="true" /></span>
        <h2 id={`${id}-title`} className="font-heading text-lg leading-tight font-semibold">{title}</h2>
        {description ? <p className="text-muted-foreground col-start-2 text-sm">{description}</p> : null}
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
        {/* Знак методики — в конце текста подписи: при переносе он не отрывается. */}
        <CardDescription className="flex items-start gap-1.5">
          <Icon className="mt-[0.2rem] size-3.5 shrink-0" aria-hidden="true" />
          <span className="min-w-0">{label}{note ? <span className="ml-1 inline-flex align-middle"><MethodNote title={label}>{note}</MethodNote></span> : null}</span>
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
        {/* Колонка закреплена: когда переключатели уходят вниз, описание не
            встаёт сбоку от заголовка в освободившуюся вторую колонку. */}
        <CardTitle as="h3" className="col-start-1 flex items-center gap-1 text-base">{title}{note ? <MethodNote title={title}>{note}</MethodNote> : null}</CardTitle>
        {description ? <CardDescription className="col-start-1">{description}</CardDescription> : null}
        {/* В узкой карточке переключатели уходят под заголовок, а не сжимают его. */}
        {action ? <CardAction className="@max-xl/card-header:col-start-1 @max-xl/card-header:row-span-1 @max-xl/card-header:row-start-auto @max-xl/card-header:justify-self-start @max-xl/card-header:mt-1">{action}</CardAction> : null}
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
    <ToggleGroup aria-label={label} variant="outline" spacing={0} className="flex-wrap" value={[value]}
      onValueChange={(next) => {
        // Base UI reports an empty selection when the pressed item is toggled off.
        const selected = options.find((option) => option.value === next[0]);
        if (selected) onChange(selected.value);
      }}>
      {options.map((option) => <ToggleGroupItem key={option.value} value={option.value}>{option.label}</ToggleGroupItem>)}
    </ToggleGroup>
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

type SortKey = "name" | "posts" | Metric | "analyzed" | "students";
// Ширины колонок и минимальная ширина таблицы — из одного списка. «Аномалии»:
// полоса уровней 96 + зазор 8 + процент 48 + отступы ячейки 16.
const TABLE_COLUMN_WIDTHS = [44, 285, 118, 90, 125, 130, 145, 140, 145, 150, 140, 172];
const TABLE_WIDTH = TABLE_COLUMN_WIDTHS.reduce((sum, width) => sum + width, 0);
const TABLE_COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: "name", label: "Вуз" },
  { key: "posts", label: "Публикаций", numeric: true },
  { key: "postsPerDay", label: "В день", numeric: true },
  { key: "subscribers", label: "Подписчики", numeric: true },
  { key: "students", label: "Студенты", numeric: true },
  { key: "views24", label: "Просмотры 24 ч", numeric: true },
  { key: "reactions24", label: "Реакции 24 ч", numeric: true },
  { key: "engagement24", label: "Вовлечённость", numeric: true },
  { key: "viewsTotal", label: "Просмотров всего", numeric: true },
  { key: "analyzed", label: "Проанализировано", numeric: true },
  { key: "anomalyShare", label: "Аномалии", numeric: true },
];

function InstitutionTable({ rows, highlights, onToggle }: {
  rows: readonly InstitutionRow[]; highlights: HighlightMap; onToggle: (id: string) => void;
}) {
  const [sort, setSort] = useState<{ key: SortKey; descending: boolean }>({ key: "views24", descending: true });
  const sorted = useMemo(() => {
    if (sort.key === "name") return [...rows].sort((a, b) => (sort.descending ? -1 : 1) * a.name.localeCompare(b.name, "ru"));
    if (sort.key === "students") return [...rows].sort((a,b) => {
      if (a.students === null && b.students === null) return a.name.localeCompare(b.name,"ru");
      if (a.students === null) return 1;
      if (b.students === null) return -1;
      return sort.descending ? b.students-a.students : a.students-b.students;
    });
    if (sort.key === "posts" || sort.key === "analyzed") {
      const key = sort.key;
      return [...rows].sort((a, b) => (sort.descending ? b[key] - a[key] : a[key] - b[key]));
    }
    return sortRows(rows, sort.key, sort.descending);
  }, [rows, sort]);
  return (
    <div className="min-w-0" data-testid="compare-table">
      <Table className="table-fixed" style={{ minWidth: TABLE_WIDTH }}>
        <colgroup>
          {TABLE_COLUMN_WIDTHS.map((width, index) => <col key={index} style={{ width }} />)}
        </colgroup>
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
                <TableCell className="max-w-[285px]">
                  <button type="button" onClick={() => onToggle(row.id)} className="flex w-full min-w-0 items-center gap-2 text-left"
                    title={color ? "Снять выделение" : "Выделить на графиках"}>
                    <span className="size-2.5 shrink-0 rounded-full border" style={{ background: color ?? "transparent" }} aria-hidden="true" />
                    <span className="min-w-0 flex-1" title={row.fullName}>
                      <span className="block truncate font-medium">{row.name}</span>
                      {row.fullName !== row.name ? <span className="text-muted-foreground block truncate text-xs">{row.fullName}</span> : null}
                    </span>
                  </button>
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatInteger(row.posts)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatValue(row.postsPerDay, "postsPerDay")}</TableCell>
                <TableCell className="text-right tabular-nums" title={row.subscribers === null ? "Замер подписчиков отсутствует" : `Подписки по доступным замерам: ${formatInteger(row.subscribers)}. Соцсетей с данными: ${row.subscriberNetworks} из ${row.connectedNetworks}. Сумма подписок не является числом уникальных людей.`}>
                  {formatCompact(row.subscribers)}{row.subscriberNetworks < row.connectedNetworks && row.subscribers !== null ? <span className="text-muted-foreground ml-1 text-[10px]" aria-label="Данные доступны не по всем соцсетям">*</span> : null}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.studentFact ? <a href={row.studentFact.sourceUrl} target="_blank" rel="noopener noreferrer"
                    className="decoration-muted-foreground/40 underline underline-offset-4 hover:decoration-foreground"
                    title={`${row.studentFact.referenceDate ?? row.studentFact.referenceYear ?? "Дата не указана"} · ${row.studentFact.sourceLabel}. ${row.studentFact.scope}`}>
                    {row.studentFact.approximate ? "≈ " : ""}{formatInteger(row.students)}
                    <span className="sr-only"> · источник численности студентов (новая вкладка)</span>
                  </a> : <span title="Проверенная численность студентов не найдена">—</span>}
                </TableCell>
                <TableCell className="text-right font-medium tabular-nums">{formatInteger(row.views24)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatInteger(row.reactions24)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatPercent(row.engagement24)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatCompact(row.viewsTotal || null)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatInteger(row.analyzed)}</TableCell>
                <TableCell className="text-right">
                  <span className="inline-flex items-center justify-end gap-2 whitespace-nowrap">
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

type Overlay = { id: string; name: string; status: string };

function OverlayRetry({ onRetry, names }: { onRetry: () => void; names?: string }) {
  return (
    <span role="status">
      Не удалось загрузить данные{names ? `: ${names}` : " вуза"}.{" "}
      <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={onRetry}>Повторить</Button>
    </span>
  );
}

/** Подпись под графиками с выделенными вузами: что ещё грузится или не пришло. */
function OverlayStatus({ overlays, onRetry }: { overlays: readonly Overlay[]; onRetry: () => void }) {
  const failed = overlays.filter((item) => item.status === "error");
  const loading = overlays.filter((item) => item.status === "loading");
  if (failed.length) return <OverlayRetry onRetry={onRetry} names={failed.map((item) => item.name).join(", ")} />;
  if (loading.length) return <span role="status">Загружаем: {loading.map((item) => item.name).join(", ")}…</span>;
  return null;
}

const SHORT_PLATFORM_NAMES: Record<DashboardPlatform, string> = {
  all: "Все", telegram: "TG", vk: "ВК", max: "MAX", rutube: "RT",
};

export function CompareDashboard({ data, period, initialPlatform, initialHighlights }: {
  data: Dashboard; period: DashboardPeriod; initialPlatform: DashboardPlatform; initialHighlights: readonly string[];
}) {
  const [platform, setPlatform] = useState(initialPlatform);
  const toolbar = useRef<HTMLDivElement>(null);
  useStuck(toolbar);
  const [activeSection, setActiveSection] = useState<(typeof SECTIONS)[number]["id"]>("summary");
  const [rankingMetric, setRankingMetric] = useState<Metric>("views24");
  const [scatter, setScatter] = useState(SCATTER_PRESETS[0]!.id);
  const [curveField, setCurveField] = useState<"views" | "reactions">("views");
  const [curveNetwork, setCurveNetwork] = useState<Network>(initialPlatform === "all" ? "telegram" : initialPlatform);
  const [highlights, setHighlights] = useState<HighlightMap>(() => highlightMap(
    initialHighlights.filter((id) => data.institutions.some((item) => item.institutionId === id)).slice(0, MAX_HIGHLIGHTS)));
  const highlightIds = useMemo(() => [...highlights.keys()], [highlights]);
  // Кнопка «Выбрать вуз» в пустом профиле переводит фокус в поиск.
  const [focusRequest, setFocusRequest] = useState(0);
  const [heatmapScope, setHeatmapScope] = useState("all");

  const rows = useMemo(() => institutionRows(data, platform), [data, platform]);
  const activeRows = useMemo(() => rows.filter((row) => row.posts > 0), [rows]);
  const summary = useMemo(() => platformSummary(data, platform, rows), [data, platform, rows]);
  const options = useMemo(() => institutionOptions(data, platform), [data, platform]);
  const labels = useMemo(() => institutionLabels(data), [data]);
  const timing = useInstitutionTiming(highlightIds, period);
  // Вуз для тепловой карты — один из выделенных; снятый вуз возвращает «все вузы».
  const heatmapId = highlights.has(heatmapScope) ? heatmapScope : "all";
  const heatmapState = heatmapId === "all" ? null : timing.states.get(heatmapId);
  const heatmapGrid = useMemo(() => timingGrid(heatmapState?.status === "ready" ? heatmapState.data : data, platform),
    [heatmapState, data, platform]);
  const overlays = useMemo(() => highlightIds.map((id) => {
    const state = timing.states.get(id);
    return { id, name: labels.get(id)?.name ?? id, color: highlights.get(id)!, status: state?.status ?? "loading",
      source: state?.status === "ready" ? state.data : null };
  }), [highlightIds, highlights, labels, timing.states]);
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

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      // The last section which passed the sticky controls owns the active tab.
      // This also works for long sections and at the very bottom of the page.
      let current: (typeof SECTIONS)[number]["id"] = "summary";
      for (const section of SECTIONS) {
        const node = document.getElementById(section.id);
        if (node && node.getBoundingClientRect().top <= 210) current = section.id;
      }
      setActiveSection(current);
    };
    const schedule = () => { if (!frame) frame = window.requestAnimationFrame(update); };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, []);

  useEffect(() => {
    const nav = document.querySelector<HTMLElement>('[data-testid="compare-section-nav"]');
    const link = nav?.querySelector<HTMLElement>(`[href="#${activeSection}"]`);
    if (!nav || !link) return;
    const left = link.offsetLeft - nav.offsetLeft;
    if (left < nav.scrollLeft || left + link.offsetWidth > nav.scrollLeft + nav.clientWidth) {
      nav.scrollTo({ left: left - 8, behavior: "smooth" });
    }
  }, [activeSection]);

  const toggle = useCallback((id: string) => setHighlights((current) => toggleHighlight(current, id)), []);
  const pickInstitution = useCallback(() => {
    toolbar.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    setFocusRequest((value) => value + 1);
  }, []);
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
      <div ref={toolbar} className={cn("p-2.5", STICKY_CONTROL_SURFACE_CLASS)}>
        <div data-testid="compare-filter-row" className="grid grid-cols-2 items-start gap-2 sm:grid-cols-[minmax(240px,1fr)_minmax(140px,1fr)] md:grid-cols-[240px_140px_minmax(0,1fr)]">
          <Tabs value={platform} onValueChange={(value) => changePlatform(value as DashboardPlatform)} className="col-span-2 min-w-0 w-full sm:col-span-1">
            <TabsList aria-label="Соцсеть" data-testid="platform-tabs" activateOnFocus className="grid w-full grid-cols-5">
              {DASHBOARD_PLATFORMS.map((value) => (
                <TabsTrigger key={value} value={value} data-value={value} className="px-1.5 text-sm">
                  <span title={PLATFORM_NAMES[value]}>{SHORT_PLATFORM_NAMES[value]}</span>
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <Tabs value={period} className="col-span-2 min-w-0 w-full sm:col-span-1">
            <TabsList aria-label="Период" className="grid w-full grid-cols-2">
              {(["7d", "30d"] as const).map((value) => (
                <TabsTrigger key={value} value={value} nativeButton={false} className="px-1.5 text-sm" title={value === "7d" ? "7 дней" : "30 дней"}
                  render={<Link href={periodHref(value)} prefetch={false} />}>
                  {value === "7d" ? "7 д" : "30 д"}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <HighlightBar options={options} labels={labels} highlights={highlights} onToggle={toggle}
            onClear={() => setHighlights(new Map())} focusRequest={focusRequest} />
        </div>
        <nav aria-label="Разделы страницы" data-testid="compare-section-nav" className="no-scrollbar -mx-2.5 mt-2 flex gap-1 overflow-x-auto px-2.5 whitespace-nowrap">
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <a key={id} href={`#${id}`} aria-current={activeSection === id ? "location" : undefined}
              className={cn(buttonVariants({ variant: activeSection === id ? "secondary" : "ghost", size: "sm" }), "shrink-0",
                activeSection === id ? "text-foreground" : "text-muted-foreground")}>
              <Icon aria-hidden="true" />{label}
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

      <Section id="ranking" title="Вузы по показателю" icon={ChartBar} description={`${activeRows.length} участников · одна шкала`}>
        <ChartCard title={METRICS[rankingMetric].label} note={METRICS[rankingMetric].hint} testId="ranking-card"
          action={<NativeSelect value={rankingMetric} onChange={(event) => setRankingMetric(event.target.value as Metric)} aria-label="Мера рейтинга">
            {RANKING_METRICS.map((metric) => <NativeSelectOption key={metric} value={metric}>{METRICS[metric].short}</NativeSelectOption>)}
          </NativeSelect>}
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
            description={highlights.size ? "Выделенные вузы" : undefined}
            note="Место вуза среди всех вузов по шести мерам: 100 — лучший, 0 — последний. «Чистота динамики» — обратная доля постов с аномалиями.">
            <RadarProfile rows={activeRows} highlights={highlights} onPick={pickInstitution} />
          </ChartCard>
        </div>
      </Section>

      <Section id="growth" title="Как набираются просмотры" icon={TrendingUp}
        description="Медиана значения поста на фиксированных часах после выхода — от первого часа до недели.">
        <ChartCard title={`${curveField === "views" ? "Просмотры" : "Реакции"} по возрасту поста · ${PLATFORM_NAMES[curveNetwork]}`} testId="curves-card"
          note="Площадки не смешиваются: просмотр в Telegram и во ВКонтакте значит разное. Тонкие линии — все вузы площадки, жирная — медиана площадки. Наведите на линию, чтобы узнать вуз, нажмите — чтобы выделить."
          action={<div className="flex flex-wrap gap-2">
            {platform === "all" ? <Segmented label="Площадка кривых" value={curveNetwork} onChange={setCurveNetwork}
              options={NETWORKS.map((network) => ({ value: network, label: PLATFORM_NAMES[network] }))} /> : null}
            <Segmented label="Мера кривых" value={curveField} onChange={setCurveField}
              options={[{ value: "views", label: "Просмотры" }, { value: "reactions", label: "Реакции" }]} />
          </div>}>
          <CurvesChart data={data} platform={curveNetwork} rows={curveRowsForNetwork} highlights={highlights} field={curveField}
            onPick={toggle} canAdd={highlights.size < MAX_HIGHLIGHTS} />
        </ChartCard>
      </Section>

      <Section id="anomalies" title="Аномальная динамика" icon={ShieldAlert}
        description="Выводы модуля анализа по постам периода. Сигнал информационный и сам по себе не доказывает накрутку.">
        <div className="grid gap-4 lg:grid-cols-3">
          <ChartCard title="Уровни анализа" description={`${formatInteger(summary.analyzed)} проанализированных постов`} testId="levels-card"
            note="Высший уровень дают сильные признаки из разных семейств методов или подтверждённый короткий рывок с плато. «С аномалиями» — уровни «выраженная аномалия» и «признаки искусственной активности».">
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
            description={`${anomalyRows.length} участников с ≥5 проанализированными постами`}
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

      <Section id="timing" title="Время и форматы" icon={CalendarClock}
        description={highlights.size ? "Когда публикуют и что работает лучше: все вузы и выделенные." : "Когда публикуют и что работает лучше — по всем вузам. Выделите вуз, чтобы сравнить его со всеми."}>
        <div className="grid gap-4 xl:grid-cols-2">
          <ChartCard title="Когда публикуют" testId="heatmap-card"
            description={`День недели и час выхода, московское время · ${heatmapId === "all" ? "все вузы" : labels.get(heatmapId)?.name}`}
            action={highlights.size ? <NativeSelect value={heatmapId} onChange={(event) => setHeatmapScope(event.target.value)} aria-label="Чьи публикации показать">
              <NativeSelectOption value="all">Все вузы</NativeSelectOption>
              {highlightIds.map((id) => <NativeSelectOption key={id} value={id}>{labels.get(id)?.name ?? id}</NativeSelectOption>)}
            </NativeSelect> : undefined}
            footer={heatmapState?.status === "error" ? <OverlayRetry onRetry={timing.retry} /> : undefined}>
            <TimingHeatmap grid={heatmapGrid} loading={heatmapState?.status === "loading"} />
          </ChartCard>
          <ChartCard title="Час выхода и охват" testId="hourly-card"
            note={`Столбцы — сколько постов всех вузов вышло в этот час; линии — медиана просмотров за первые сутки у постов этого часа: серая — все вузы, цветные — выделенные (часы, где у вуза меньше ${OVERLAY_MIN_POSTS} постов, пропущены).`}
            footer={<OverlayStatus overlays={overlays} onRetry={timing.retry} />}>
            <HourlyReachChart data={data} platform={platform} overlays={overlays} />
          </ChartCard>
        </div>
        <div className="mt-4">
          <ChartCard title="Форматы публикаций" testId="types-card"
            description={highlights.size ? "Доля каждого формата в публикациях и медиана просмотров за 24 часа: все вузы и выделенные"
              : "Сколько публикаций каждого формата и медиана их просмотров за 24 часа"}
            note="Основные форматы — текст, фото, альбом и видео; опросы, документы, ссылки, стикеры и другие редкие форматы собраны в «Прочее»."
            footer={<OverlayStatus overlays={overlays} onRetry={timing.retry} />}>
            <TypesChart data={data} platform={platform} overlays={overlays} />
          </ChartCard>
        </div>
      </Section>

      <Section id="table" title="Все вузы" icon={ChartNetwork} description="Сортировка — по клику на заголовок, выделение — по клику на вуз.">
        <Card className="py-2"><CardContent className="px-2"><InstitutionTable rows={rows} highlights={highlights} onToggle={toggle} /></CardContent></Card>
      </Section>
    </div>
  );
}
