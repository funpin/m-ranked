"use client";
import { Empty, EmptyContent, EmptyDescription } from "@/components/ui/empty";

import { memo, useMemo, useState, type ComponentProps } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, Label, Line, LineChart, Pie, PieChart,
  PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ReferenceLine, Scatter, ScatterChart,
  XAxis, YAxis, ZAxis, useXAxisScale, useYAxisScale,
} from "recharts";
import { Button } from "@/components/ui/button";
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import {
  LEVEL_COLORS, LEVEL_NAMES, MAX_HIGHLIGHTS, METRICS, NETWORKS, PLATFORM_COLORS, PLATFORM_NAMES,
  curveRows, dailyRows, formatCompact, formatInteger, formatPercent, formatValue, hourLabel, hourlyReach, incompleteDay,
  levelSharesByPlatform, median, metricValue, percentileRank, sortRows,
  type Dashboard, type DashboardPlatform, type InstitutionRow, type Metric, type Network,
} from "@/lib/compare-dashboard";
import { hourlyOverlay, overlayKey, typeComparison, type TimingOverlay } from "@/lib/compare-timing";

/** Выделенные вузы: id → цвет. Остальные рисуются нейтрально. */
export type Highlights = ReadonlyMap<string, string>;

const BASE_BAR = "var(--chart-2)";
const MUTED_BAR = "color-mix(in oklch, var(--chart-2) 45%, transparent)";
const dayLabel = (value: string) => {
  const [, month, day] = value.split("-");
  return `${Number(day)}.${month}`;
};

/** Подписи осей: только там, где без них неясно, что откладывается. Цвет
 *  подписи — цвет ряда, если на графике две шкалы. Ширина оси Y под
 *  повёрнутую подпись больше на AXIS_TITLE_GUTTER. */
const AXIS_TITLE_GUTTER = 16;
type AxisLabel = ComponentProps<typeof XAxis>["label"];
/** Ось X с подписью выше обычной: деления сверху, подпись — под ними. */
const X_TITLE_HEIGHT = 44;
function xTitle(value: string): AxisLabel {
  return { value, position: "insideBottom", offset: 0, style: { fontSize: 11, fill: "var(--muted-foreground)" } };
}
function yTitle(value: string, side: "left" | "right" = "left", color = "var(--muted-foreground)"): AxisLabel {
  return { value, angle: side === "left" ? -90 : 90, position: side === "left" ? "insideLeft" : "insideRight",
    style: { fontSize: 11, fill: color, textAnchor: "middle" } };
}

const NO_OVERLAYS: readonly TimingOverlay[] = [];

/** Название вуза у строки рейтинга: одна строка с многоточием — Recharts
 *  иначе переносит длинное имя, и оно наезжает на соседние строки. Полное
 *  название — в подсказке; нажатие выбирает вуз, как и клик по строке. */
const NAME_TICK_CHARS = 18;
function NameTick({ x, y, payload, rows, highlights, onPick }: {
  x?: number | string; y?: number | string; payload?: { value?: unknown; index?: number };
  rows: readonly { id: string; name: string; fullName: string }[]; highlights: Highlights; onPick?: Pick;
}) {
  const row = payload?.index === undefined ? undefined : rows[payload.index];
  const text = String(payload?.value ?? "");
  const color = row ? highlights.get(row.id) : undefined;
  return (
    <text x={x} y={y} dy={4} textAnchor="end" fontSize={11} fontWeight={color ? 700 : 400}
      fill={color ?? "var(--muted-foreground)"} className={onPick && row ? "cursor-pointer" : undefined}
      onClick={onPick && row ? () => onPick(row.id) : undefined}>
      <title>{row?.fullName ?? text}</title>
      {text.length > NAME_TICK_CHARS ? `${text.slice(0, NAME_TICK_CHARS - 1)}…` : text}
    </text>
  );
}

/** Круглая верхняя граница шкалы: 1, 2, 2,5 или 5 × 10ⁿ, не меньше значения. */
function niceCeil(value: number) {
  const power = 10 ** Math.floor(Math.log10(value));
  return [1, 2, 2.5, 5, 10].map((step) => step * power).find((bound) => bound >= value)!;
}

/** Выбор вуза кликом по графику: в рейтингах — по всей строке вуза, даже если
 *  столбик почти нулевой. Повторный клик снимает выделение, как в таблице. */
type Pick = (id: string) => void;
function rowPicker<T extends { id: string }>(rows: readonly T[], onPick?: Pick) {
  return onPick ? (state: { activeIndex?: number | string | null }) => {
    const row = state.activeIndex === null || state.activeIndex === undefined ? undefined : rows[Number(state.activeIndex)];
    if (row) onPick(row.id);
  } : undefined;
}
/** Клик по самому столбику выбирает вуз сразу и не доходит до строки:
 *  иначе выделение переключилось бы дважды. */
function barPicker(onPick?: Pick) {
  return onPick ? (item: unknown, _index: number, event?: { stopPropagation?: () => void }) => {
    event?.stopPropagation?.();
    const id = (item as { payload?: { id?: string } }).payload?.id;
    if (id) onPick(id);
  } : undefined;
}
const pickNote = (highlights: Highlights, id: string) => highlights.has(id)
  ? "Нажмите, чтобы снять выделение"
  : highlights.size < MAX_HIGHLIGHTS ? "Нажмите, чтобы выделить вуз" : `Выделено ${MAX_HIGHLIGHTS} из ${MAX_HIGHLIGHTS}`;

const PARTIAL_LABEL = "день не закончился";
/** В подсказке незаконченный день показывается один раз: пунктирный ряд
 *  повторяет значение предыдущего дня, только чтобы провести линию. */
function withoutPartialEchoes<T extends { dataKey?: unknown; payload?: Record<string, unknown> }>(payload: readonly T[] | undefined) {
  return (payload ?? []).filter((item) => {
    const key = String(item.dataKey ?? "");
    return !key.endsWith("_partial") || item.payload?.[key.slice(0, -"_partial".length)] == null;
  });
}

function TooltipBox({ title, lines, note }: { title: string; lines: [string, string][]; note?: string }) {
  return (
    // Ширина ограничена: длинное полное название переносится, а не выталкивает
    // числа за край карточки.
    <div className="border-border/50 bg-background grid w-max max-w-72 min-w-40 gap-1 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl">
      <div className="font-medium text-pretty">{title}</div>
      {lines.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-4">
          <span className="text-muted-foreground">{label}</span>
          <span className="text-foreground shrink-0 font-mono font-medium whitespace-nowrap tabular-nums">{value}</span>
        </div>
      ))}
      {note ? <div className="text-muted-foreground">{note}</div> : null}
    </div>
  );
}

/** Сортировка всех вузов по одной мере: горизонтальные полосы, высота растёт с
 *  числом вузов, поэтому ограничения на их число нет. Пунктир — медиана. */
export function RankingChart({ rows, metric, highlights, descending = true, onPick }: {
  rows: readonly InstitutionRow[]; metric: Metric; highlights: Highlights; descending?: boolean; onPick?: Pick;
}) {
  const data = useMemo(() => sortRows(rows, metric, descending)
    .filter((row) => metricValue(row, metric) !== null)
    .map((row) => ({ id: row.id, name: row.name, fullName: row.fullName, value: metricValue(row, metric)!, row })), [rows, metric, descending]);
  const middle = median(data.map((item) => item.value));
  const config = { value: { label: METRICS[metric].short, color: BASE_BAR } } satisfies ChartConfig;
  if (!data.length) return <EmptyChart />;
  const anyHighlight = highlights.size > 0;
  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height: Math.max(220, data.length * 22 + 48) }}
      data-testid="ranking-chart" role="img" aria-label={`Вузы по показателю: ${METRICS[metric].label}`}>
      <BarChart data={data} layout="vertical" margin={{ left: 4, right: 48, top: 22, bottom: 8 }} barCategoryGap={3}
        onClick={rowPicker(data, onPick)} className={onPick ? "cursor-pointer" : undefined}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tickFormatter={(value) => formatValue(value, metric)} tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey="name" width={132} tickLine={false} axisLine={false} interval={0}
          tick={(props) => <NameTick {...props} rows={data} highlights={highlights} onPick={onPick} />} />
        <ChartTooltip cursor={{ fillOpacity: 0.4 }} content={({ active, payload }) => {
          const item = active ? payload?.[0]?.payload as (typeof data)[number] | undefined : undefined;
          if (!item) return null;
          return <TooltipBox title={item.row.fullName} lines={[
            [METRICS[metric].short, formatValue(item.value, metric)],
            ["Публикаций", formatInteger(item.row.posts)],
            ["Проанализировано", formatInteger(item.row.analyzed)],
          ]} note={onPick ? pickNote(highlights, item.id) : undefined} />;
        }} />
        {middle !== null ? (
          <ReferenceLine x={middle} stroke="var(--foreground)" strokeOpacity={0.5} strokeDasharray="4 4">
            <Label value={`медиана ${formatValue(middle, metric)}`} position="top" fontSize={10} fill="var(--muted-foreground)" />
          </ReferenceLine>
        ) : null}
        <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false} onClick={barPicker(onPick)}
          label={{ position: "right", fontSize: 10, fill: "var(--muted-foreground)", formatter: (value: unknown) => formatValue(value as number, metric) }}>
          {data.map((item) => (
            <Cell key={item.id} fill={highlights.get(item.id) ?? (anyHighlight ? MUTED_BAR : BASE_BAR)} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}

/** Карта вузов в двух мерах сразу; размер точки — подписчики. Логарифмическая
 *  шкала: охваты вузов различаются на порядки. */
export function ScatterMap({ rows, x, y, highlights, onPick }: {
  rows: readonly InstitutionRow[]; x: Metric; y: Metric; highlights: Highlights; onPick?: Pick;
}) {
  const points = useMemo(() => rows
    .map((row) => ({ id: row.id, name: row.fullName, short: row.name, x: metricValue(row, x), y: metricValue(row, y), z: Math.max(row.subscribers ?? 0, 1) }))
    .filter((point): point is typeof point & { x: number; y: number } => point.x !== null && point.y !== null && point.x > 0 && point.y > 0),
  [rows, x, y]);
  const config = { y: { label: METRICS[y].short, color: BASE_BAR } } satisfies ChartConfig;
  if (points.length < 2) return <EmptyChart />;
  const midX = median(points.map((point) => point.x));
  const midY = median(points.map((point) => point.y));
  const anyHighlight = highlights.size > 0;
  return (
    <ChartContainer config={config} className="aspect-auto h-[360px] w-full" data-testid="scatter-chart" role="img"
      aria-label={`${METRICS[x].short} и ${METRICS[y].short} по вузам`}>
      <ScatterChart margin={{ left: 8, right: 16, top: 12 }}>
        <CartesianGrid />
        <XAxis type="number" dataKey="x" scale="log" domain={["auto", "auto"]} tickFormatter={(value) => formatValue(value, x)} tickLine={false}
          height={X_TITLE_HEIGHT} label={xTitle(METRICS[x].short)} />
        <YAxis type="number" dataKey="y" scale="log" domain={["auto", "auto"]} tickFormatter={(value) => formatValue(value, y)} tickLine={false}
          width={56 + AXIS_TITLE_GUTTER} label={yTitle(METRICS[y].short)} />
        <ZAxis type="number" dataKey="z" range={[30, 420]} scale="sqrt" />
        {midX !== null ? <ReferenceLine x={midX} stroke="var(--border)" strokeDasharray="4 4" /> : null}
        {midY !== null ? <ReferenceLine y={midY} stroke="var(--border)" strokeDasharray="4 4" /> : null}
        <ChartTooltip cursor={false} content={({ active, payload }) => {
          const point = active ? payload?.[0]?.payload as (typeof points)[number] | undefined : undefined;
          if (!point) return null;
          return <TooltipBox title={point.name} lines={[
            [METRICS[x].short, formatValue(point.x, x)], [METRICS[y].short, formatValue(point.y, y)],
            ["Подписчики", formatCompact(point.z)],
          ]} note={onPick ? pickNote(highlights, point.id) : undefined} />;
        }} />
        <Scatter data={points} isAnimationActive={false} className={onPick ? "cursor-pointer" : undefined}
          onClick={onPick ? (point: { payload?: { id?: string } }) => { if (point.payload?.id) onPick(point.payload.id); } : undefined}>
          {points.map((point) => {
            const color = highlights.get(point.id);
            return <Cell key={point.id} fill={color ?? BASE_BAR} fillOpacity={color ? 0.95 : anyHighlight ? 0.2 : 0.55}
              stroke={color ? "var(--background)" : "none"} strokeWidth={color ? 2 : 0} />;
          })}
        </Scatter>
      </ScatterChart>
    </ChartContainer>
  );
}

/** Серые кривые всех вузов одним слоем: каждая линия отзывается на курсор и
 *  нажатие, поэтому вуз, идущий выше остальных, находится без перебора.
 *  Невидимая широкая обводка — зона попадания по тонкой линии. */
const CurveBackdrop = memo(function CurveBackdrop({ rows, ids, hovered, onHover, onPick }: {
  rows: readonly Record<string, number | null>[]; ids: readonly string[]; hovered: string | null;
  onHover: (id: string | null) => void; onPick: (id: string) => void;
}) {
  const x = useXAxisScale();
  const y = useYAxisScale();
  // Пути пересчитываются только при смене данных или масштаба, не на наведение.
  const paths = useMemo(() => !x || !y ? [] : ids.map((id) => {
    const points = rows.flatMap((row) => {
      const value = row[id];
      const px = x(row.hour!), py = value === null || value === undefined ? undefined : y(value);
      return px === undefined || py === undefined ? [] : [`${px},${py}`];
    });
    return { id, d: points.length > 1 ? `M${points.join("L")}` : null };
  }), [x, y, rows, ids]);
  return (
    <g data-testid="curves-backdrop" onPointerLeave={() => onHover(null)}>
      {paths.map(({ id, d }) => d ? (
        <g key={id} data-institution={id} className="cursor-pointer" onPointerEnter={() => onHover(id)} onClick={() => onPick(id)}>
          <path d={d} fill="none" stroke="var(--muted-foreground)" strokeOpacity={hovered === id ? 0.95 : 0.14}
            strokeWidth={hovered === id ? 2 : 1} />
          <path d={d} fill="none" stroke="transparent" strokeWidth={9} />
        </g>
      ) : null)}
    </g>
  );
});

/** Как набираются просмотры: медиана всех вузов площадки — жирная линия,
 *  выделенные — цветом, остальные — тонкий фон, чтобы видеть разброс.
 *  Наведение на фоновую линию называет вуз, нажатие — выделяет его. */
export function CurvesChart({ data, platform, rows, highlights, field, onPick }: {
  data: Dashboard; platform: Network; rows: readonly InstitutionRow[]; highlights: Highlights; field: "views" | "reactions";
  onPick: (id: string) => void;
}) {
  const ids = useMemo(() => rows.map((row) => row.id), [rows]);
  const chart = useMemo(() => curveRows(data, platform, ids, field), [data, platform, ids, field]);
  const [hovered, setHovered] = useState<string | null>(null);
  const names = useMemo(() => new Map(rows.map((row) => [row.id, row.name])), [rows]);
  const background = useMemo(() => ids.filter((id) => !highlights.has(id)), [ids, highlights]);
  const pick = useMemo(() => (id: string) => { setHovered(null); onPick(id); }, [onPick]);
  const config = useMemo(() => {
    const result: ChartConfig = { median: { label: `Медиана ${PLATFORM_NAMES[platform]}`, color: "var(--foreground)" } };
    for (const [id, color] of highlights) result[id] = { label: names.get(id) ?? id, color };
    return result;
  }, [platform, highlights, names]);
  const canAdd = highlights.size < MAX_HIGHLIGHTS;
  // Шкала — по всем линиям, а не только по нарисованным рядам Recharts: иначе
  // верхние вузы уходят за край и в них не попасть.
  const yMax = useMemo(() => niceCeil(Math.max(1, ...chart.flatMap((row) =>
    Object.entries(row).flatMap(([key, value]) => key !== "hour" && typeof value === "number" ? [value] : [])))), [chart]);
  if (!chart.some((point) => point.median !== null)) return <EmptyChart />;
  const measure = field === "views" ? "Просмотры" : "Реакции";
  return (
    <ChartContainer config={config} className="aspect-auto h-[360px] w-full" data-testid="curves-chart" role="img"
      aria-label="Накопление по часам после публикации">
      <LineChart data={chart} margin={{ left: 8, right: 16, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="hour" type="number" scale="log" domain={[data.hours[0] ?? 1, data.hours.at(-1) ?? 168]}
          ticks={data.hours} tickFormatter={(value) => hourLabel(Number(value))} interval="preserveStartEnd" minTickGap={6}
          tickLine={false} axisLine={false}
          height={X_TITLE_HEIGHT} label={xTitle("Время после выхода поста")} />
        <YAxis domain={[0, yMax]} tickFormatter={(value) => formatCompact(value)} tickLine={false} axisLine={false}
          width={52 + AXIS_TITLE_GUTTER} label={yTitle(`${measure}, медиана`)} />
        <CurveBackdrop rows={chart} ids={background} hovered={hovered} onHover={setHovered} onPick={pick} />
        <ChartTooltip content={(props) => {
          const hour = Number(props.label);
          const point = chart.find((row) => row.hour === hour);
          if (hovered && point) {
            return <TooltipBox title={names.get(hovered) ?? ""} lines={[
              [`${measure} на ${hourLabel(hour)}`, formatInteger(point[hovered] ?? null)],
              [`Медиана ${PLATFORM_NAMES[platform]}`, formatInteger(point.median ?? null)],
            ]} note={canAdd ? "Нажмите на линию, чтобы выделить вуз" : `Выделено ${MAX_HIGHLIGHTS} из ${MAX_HIGHLIGHTS} — снимите вуз, чтобы добавить`} />;
          }
          return <ChartTooltipContent active={props.active} payload={props.payload} label={props.label} indicator="line" labelFormatter={(_, payload) => `${hourLabel(Number(payload?.[0]?.payload?.hour))} после выхода`}
            valueFormatter={(value) => formatInteger(Number(value))} />;
        }} />
        <Line dataKey="median" stroke="var(--color-median)" strokeWidth={3} dot={{ r: 3 }} isAnimationActive={false} connectNulls />
        {[...highlights.keys()].filter((id) => ids.includes(id)).map((id) => (
          <Line key={id} dataKey={id} stroke={`var(--color-${id})`} strokeWidth={2.25} dot={{ r: 2.5 }} isAnimationActive={false} connectNulls />
        ))}
        <ChartLegend itemSorter={null} content={<ChartLegendContent />} />
      </LineChart>
    </ChartContainer>
  );
}

/** Уровни анализа за период: кольцо с долей аномалий в центре. */
export function LevelsDonut({ levels }: { levels: readonly number[] }) {
  const total = levels.reduce((sum, value) => sum + value, 0);
  const data = levels.map((count, level) => ({ level: `level${level}`, name: LEVEL_NAMES[level], count, fill: `var(--color-level${level})` }));
  const config = Object.fromEntries(LEVEL_NAMES.map((name, level) => [`level${level}`, { label: name, color: LEVEL_COLORS[level] }])) satisfies ChartConfig;
  const anomalous = total ? ((levels[2]! + levels[3]!) * 100) / total : null;
  if (!total) return <EmptyChart />;
  return (
    <ChartContainer config={config} className="mx-auto aspect-square h-[240px]" data-testid="levels-donut" role="img"
      aria-label={`Доля постов с аномалиями ${formatPercent(anomalous)}`}>
      <PieChart>
        <ChartTooltip content={<ChartTooltipContent nameKey="level" hideLabel />} />
        <Pie data={data} dataKey="count" nameKey="level" innerRadius={62} outerRadius={96} strokeWidth={3} isAnimationActive={false}>
          <Label content={({ viewBox }) => {
            if (!viewBox || !("cx" in viewBox)) return null;
            return (
              <text x={viewBox.cx} y={viewBox.cy} textAnchor="middle" dominantBaseline="middle">
                <tspan x={viewBox.cx} y={viewBox.cy} className="fill-foreground text-2xl font-bold">{formatPercent(anomalous)}</tspan>
                <tspan x={viewBox.cx} y={(viewBox.cy ?? 0) + 20} className="fill-muted-foreground text-[11px]">с аномалиями</tspan>
              </text>
            );
          }} />
        </Pie>
      </PieChart>
    </ChartContainer>
  );
}

/** Состав уровней по площадкам: каждая полоса — 100 % проанализированных постов. */
export function LevelsByPlatform({ data, institutionId = null }: { data: Dashboard; institutionId?: string | null }) {
  const rows = useMemo(() => levelSharesByPlatform(data, institutionId), [data, institutionId]);
  const config = Object.fromEntries(LEVEL_NAMES.map((name, level) => [`level${level}`, { label: name, color: LEVEL_COLORS[level] }])) satisfies ChartConfig;
  if (!rows.length) return <EmptyChart text="У вуза нет проанализированных постов за период." />;
  return (
    <ChartContainer config={config} className="aspect-auto h-[240px] w-full" data-testid="levels-by-platform" role="img"
      aria-label="Уровни анализа по площадкам">
      <BarChart data={rows} layout="vertical" stackOffset="expand" margin={{ left: 4, right: 12 }}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tickFormatter={(value) => `${Math.round(value * 100)}%`} tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey="platform" width={84} tickLine={false} axisLine={false} />
        <ChartTooltip content={<ChartTooltipContent valueFormatter={(value) => formatPercent(Number(value))} />} />
        {LEVEL_NAMES.map((_, level) => (
          <Bar key={level} dataKey={`level${level}`} stackId="levels" fill={`var(--color-level${level})`} isAnimationActive={false}
            radius={level === 0 ? [4, 0, 0, 4] : level === 3 ? [0, 4, 4, 0] : 0} />
        ))}
        <ChartLegend content={<ChartLegendContent />} />
      </BarChart>
    </ChartContainer>
  );
}

/** Незаконченный день: тот же цвет пунктиром, без отдельной записи в легенде. */
function partialLines(keys: readonly { key: string; yAxisId?: string; dashed?: boolean }[]) {
  return keys.map(({ key, yAxisId, dashed }) => (
    <Line key={`${key}_partial`} yAxisId={yAxisId} dataKey={`${key}_partial`} stroke={`var(--color-${key})`} strokeWidth={2}
      strokeDasharray={dashed ? "1 4" : "3 4"} dot={false} type="monotone" connectNulls isAnimationActive={false} legendType="none" />
  ));
}

function partialConfig(config: ChartConfig) {
  for (const [key, item] of Object.entries(config)) config[`${key}_partial`] = { ...item, label: `${item.label}, ${PARTIAL_LABEL}` };
  return config;
}

/** Динамика по дням: каждая линия показывает свою площадку, без накопления. */
export function DailyChart({ data, platform }: { data: Dashboard; platform: DashboardPlatform }) {
  const rows = useMemo(() => dailyRows(data), [data]);
  const partial = incompleteDay(data);
  const networks: readonly Network[] = platform === "all" ? NETWORKS : [platform];
  const anomaly = `anomaly_${platform}`;
  const config: ChartConfig = { [anomaly]: { label: "Доля аномалий", color: "var(--chart-10)" } };
  for (const network of networks) config[`posts_${network}`] = { label: PLATFORM_NAMES[network], color: PLATFORM_COLORS[network] };
  partialConfig(config);
  if (!rows.length) return <EmptyChart />;
  return (
    <ChartContainer config={config} className="aspect-auto h-[300px] w-full" data-testid="daily-chart" role="img"
      aria-label="Публикации и доля аномалий по дням">
      <ComposedChart data={rows} margin={{ left: 4, right: 4, top: 14 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="day" tickFormatter={dayLabel} tickLine={false} axisLine={false} minTickGap={16} />
        <YAxis yAxisId="posts" tickLine={false} axisLine={false} width={40 + AXIS_TITLE_GUTTER} label={yTitle("Публикаций в день")} />
        <YAxis yAxisId="share" orientation="right" tickFormatter={(value) => `${value}%`} tickLine={false} axisLine={false}
          width={40 + AXIS_TITLE_GUTTER} label={yTitle("Доля аномалий", "right", "var(--chart-10)")} />
        <ChartTooltip content={(props) => <ChartTooltipContent active={props.active} label={props.label} payload={withoutPartialEchoes(props.payload)}
          labelFormatter={(value) => `${dayLabel(String(value))}${value === partial ? `, ${PARTIAL_LABEL}` : ""}`}
          valueFormatter={(value, name) => String(name).startsWith("anomaly") ? formatPercent(Number(value)) : formatInteger(Number(value))} />} />
        {partial ? <ReferenceLine yAxisId="posts" x={partial} stroke="var(--border)" strokeDasharray="2 3">
          <Label value={PARTIAL_LABEL} position="insideTopRight" fontSize={10} fill="var(--muted-foreground)" />
        </ReferenceLine> : null}
        {networks.map((network) => (
          <Line key={network} yAxisId="posts" dataKey={`posts_${network}`} type="monotone"
            stroke={`var(--color-posts_${network})`} strokeWidth={2} dot={false} isAnimationActive={false} />
        ))}
        <Line yAxisId="share" dataKey={anomaly} stroke={`var(--color-${anomaly})`} strokeWidth={2}
          strokeDasharray="5 4" dot={false} type="monotone" connectNulls isAnimationActive={false} />
        {partial ? partialLines([...networks.map((network) => ({ key: `posts_${network}`, yAxisId: "posts" })),
          { key: anomaly, yAxisId: "share", dashed: true }]) : null}
        <ChartLegend content={<ChartLegendContent />} />
      </ComposedChart>
    </ChartContainer>
  );
}

/** Час выхода: сколько публикуют и сколько типичный пост набирает за сутки.
 *  Выделенные вузы — своими линиями медианы поверх общей. */
export function HourlyReachChart({ data, platform, overlays = NO_OVERLAYS }: {
  data: Dashboard; platform: DashboardPlatform; overlays?: readonly TimingOverlay[];
}) {
  const rows = useMemo(() => {
    const base: Record<string, string | number | null>[] = hourlyReach(data, platform);
    for (const overlay of overlays) {
      hourlyOverlay(overlay.source, platform).forEach((views, hour) => { base[hour]![overlayKey("views", overlay.id)] = views; });
    }
    return base;
  }, [data, platform, overlays]);
  const compare = overlays.length > 0;
  const config: ChartConfig = {
    posts: { label: "Публикаций, все вузы", color: "var(--chart-9)" },
    views24: { label: compare ? "Все вузы" : "Просмотры за 24 ч, медиана", color: compare ? "var(--muted-foreground)" : "var(--chart-3)" },
  };
  for (const overlay of overlays) config[overlayKey("views", overlay.id)] = { label: overlay.name, color: overlay.color };
  return (
    <ChartContainer config={config} className="aspect-auto h-[300px] w-full" data-testid="hourly-chart" role="img"
      aria-label="Публикации и охват по часу выхода">
      <ComposedChart data={rows} margin={{ left: 4, right: 4, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="hour" tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={10} height={X_TITLE_HEIGHT} label={xTitle("Час выхода, московское время")} />
        <YAxis yAxisId="posts" tickLine={false} axisLine={false} width={40 + AXIS_TITLE_GUTTER}
          label={yTitle("Публикаций", "left", "var(--chart-9)")} />
        <YAxis yAxisId="views" orientation="right" tickFormatter={(value) => formatCompact(value)} tickLine={false} axisLine={false}
          width={48 + AXIS_TITLE_GUTTER} label={yTitle("Просмотры за 24 ч, медиана", "right", compare ? undefined : "var(--chart-3)")} />
        <ChartTooltip content={<ChartTooltipContent valueFormatter={(value) => formatInteger(Number(value))} />} />
        <Bar yAxisId="posts" dataKey="posts" fill="var(--color-posts)" fillOpacity={compare ? 0.3 : 0.55} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        <Line yAxisId="views" dataKey="views24" stroke="var(--color-views24)" strokeWidth={compare ? 2 : 2.25}
          strokeDasharray={compare ? "4 3" : undefined} dot={false} type="monotone" connectNulls isAnimationActive={false} />
        {overlays.map((overlay) => (
          <Line key={overlay.id} yAxisId="views" dataKey={overlayKey("views", overlay.id)} stroke={`var(--color-${overlayKey("views", overlay.id)})`}
            strokeWidth={2.25} dot={{ r: 2 }} type="monotone" isAnimationActive={false} />
        ))}
        <ChartLegend itemSorter={null} content={<ChartLegendContent />} />
      </ComposedChart>
    </ChartContainer>
  );
}

/** Форматы публикаций: две панели с общим порядком форматов, у каждой —
 *  своя подписанная шкала. С выделенными вузами левая панель показывает долю
 *  формата: у вуза сотни постов, у всех вузов — десятки тысяч. */
export function TypesChart({ data, platform, overlays = NO_OVERLAYS }: {
  data: Dashboard; platform: DashboardPlatform; overlays?: readonly TimingOverlay[];
}) {
  const rows = useMemo(() => typeComparison(data, platform, overlays), [data, platform, overlays]);
  if (!rows.length) return <EmptyChart />;
  const compare = overlays.length > 0;
  const height = Math.max(200, rows.length * (28 + overlays.length * 12) + 72);
  const config: ChartConfig = {
    base: { label: compare ? "Все вузы" : "Публикаций", color: compare ? "var(--muted-foreground)" : "var(--chart-5)" },
    views: { label: compare ? "Все вузы" : "Просмотры за 24 ч, медиана", color: compare ? "var(--muted-foreground)" : "var(--chart-11)" },
  };
  for (const overlay of overlays) config[overlay.id] = { label: overlay.name, color: overlay.color };
  const panel = (kind: "count" | "views") => {
    const valueKey = kind === "views" ? "views24" : compare ? "share" : "posts";
    const format = (value: unknown) => kind === "views" ? formatCompact(value as number)
      : compare ? formatPercent(value as number) : formatInteger(value as number);
    const title = kind === "views" ? "Просмотры за 24 ч, медиана" : compare ? "Доля публикаций, %" : "Публикаций";
    return (
      <ChartContainer config={config} className="aspect-auto w-full" style={{ height }} data-testid={`types-chart-${kind}`}
        role="img" aria-label={`Форматы публикаций: ${title}`}>
        <BarChart data={rows} layout="vertical" margin={{ left: 4, right: 44 }} barGap={1}>
          <CartesianGrid horizontal={false} />
          <XAxis type="number" tickFormatter={format} tickLine={false} axisLine={false} height={X_TITLE_HEIGHT} label={xTitle(title)} />
          <YAxis type="category" dataKey="type" width={72} tickLine={false} axisLine={false} />
          <ChartTooltip content={({ active, payload }) => {
            const item = active ? payload?.[0]?.payload as (typeof rows)[number] | undefined : undefined;
            if (!item) return null;
            return <TooltipBox title={String(item.type)} lines={[
              ["Все вузы: публикаций", `${formatInteger(item.posts as number)} (${formatPercent(item.share as number)})`],
              ["Все вузы: просмотры за 24 ч", formatInteger(item.views24 as number | null)],
              ...overlays.flatMap((overlay): [string, string][] => [
                [`${overlay.name}: публикаций`, `${formatInteger(item[overlayKey("posts", overlay.id)] as number)} (${formatPercent(item[overlayKey("share", overlay.id)] as number)})`],
                [`${overlay.name}: просмотры за 24 ч`, formatInteger(item[overlayKey("views", overlay.id)] as number | null)],
              ]),
            ]} />;
          }} />
          <Bar dataKey={valueKey} name={kind === "views" ? "views" : "base"} fill={`var(--color-${kind === "views" ? "views" : "base"})`}
            fillOpacity={compare ? 0.45 : 1} radius={4} isAnimationActive={false}
            label={{ position: "right", fontSize: 10, fill: "var(--muted-foreground)", formatter: format }} />
          {overlays.map((overlay) => (
            <Bar key={overlay.id} dataKey={overlayKey(kind === "views" ? "views" : "share", overlay.id)} name={overlay.id}
              fill={`var(--color-${overlay.id})`} radius={4} isAnimationActive={false} />
          ))}
          {/* Ключи рядов — доли и медианы, а подписи в config — по name: легенда ищет по нему. */}
          {compare ? <ChartLegend itemSorter={null} content={<ChartLegendContent nameKey="value" />} /> : null}
        </BarChart>
      </ChartContainer>
    );
  };
  return <div className="grid gap-6 xl:grid-cols-2" data-testid="types-chart">{panel("count")}{panel("views")}</div>;
}

const RADAR_AXES: { metric: Metric; label: string; inverse?: boolean }[] = [
  { metric: "views24", label: "Охват поста" },
  { metric: "reactions24", label: "Реакции" },
  { metric: "engagement24", label: "Вовлечённость" },
  { metric: "postsPerDay", label: "Активность" },
  { metric: "subscribers", label: "Аудитория" },
  { metric: "anomalyShare", label: "Чистота динамики", inverse: true },
];

/** Профиль вуза: место среди всех вузов по шести мерам, 100 — лучший. Меры
 *  разного масштаба приведены к процентилям, поэтому их можно сравнивать. */
export function RadarProfile({ rows, highlights, onPick }: { rows: readonly InstitutionRow[]; highlights: Highlights; onPick: () => void }) {
  const chosen = rows.filter((row) => highlights.has(row.id));
  const data = RADAR_AXES.map((axis) => {
    const point: Record<string, string | number | null> = { axis: axis.label };
    for (const row of chosen) point[row.id] = percentileRank(rows, row, axis.metric, axis.inverse);
    return point;
  });
  const config: ChartConfig = {};
  for (const row of chosen) config[row.id] = { label: row.name, color: highlights.get(row.id)! };
  if (!chosen.length) {
    return (
      <Empty className="h-[300px] rounded-lg border p-4" data-testid="radar-empty">
        <EmptyDescription className="text-sm">{highlights.size
          ? "У выделенных вузов нет публикаций на этой площадке за период."
          : "Выберите до шести вузов, чтобы сравнить их профили по шести мерам."}</EmptyDescription>
        <EmptyContent><Button variant="outline" size="sm" onClick={onPick}>Выбрать вуз</Button></EmptyContent>
      </Empty>
    );
  }
  return (
    <div className="min-w-0">
      <ChartContainer config={config} className="mx-auto aspect-auto h-[300px] w-full max-w-[440px]" data-testid="radar-chart" role="img"
        aria-label="Профиль выделенных вузов">
        <RadarChart data={data} outerRadius="60%" margin={{ top: 14, right: 36, bottom: 14, left: 36 }}>
          <ChartTooltip content={<ChartTooltipContent valueFormatter={(value) => `${value} из 100`} />} />
          <PolarGrid />
          <PolarAngleAxis dataKey="axis" tick={{ fontSize: 11 }} />
          <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
          {chosen.map((row) => (
            <Radar key={row.id} dataKey={row.id} stroke={`var(--color-${row.id})`} fill={`var(--color-${row.id})`}
              fillOpacity={chosen.length > 2 ? 0.08 : 0.2} strokeWidth={2} isAnimationActive={false} />
          ))}
        </RadarChart>
      </ChartContainer>
      <div className="mt-1 flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs" aria-label="Выделенные вузы">
        {chosen.map((row) => <span key={row.id} className="inline-flex max-w-full min-w-0 items-center gap-1.5">
          <span className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: highlights.get(row.id) }} aria-hidden="true" />
          <span className="truncate" title={row.fullName}>{row.name}</span>
        </span>)}
      </div>
    </div>
  );
}

/** Присутствие в соцсетях: публикации вуза по площадкам, все вузы. */
export function PresenceChart({ rows, highlights, onPick }: { rows: readonly InstitutionRow[]; highlights: Highlights; onPick?: Pick }) {
  const data = useMemo(() => [...rows]
    .filter((row) => row.posts > 0)
    .sort((left, right) => right.posts - left.posts)
    .map((row) => ({ id: row.id, name: row.name, fullName: row.fullName, ...row.byNetwork })), [rows]);
  const config = Object.fromEntries(NETWORKS.map((network) => [network, { label: PLATFORM_NAMES[network], color: PLATFORM_COLORS[network] }])) satisfies ChartConfig;
  if (!data.length) return <EmptyChart />;
  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height: data.length * 20 + 94 }}
      data-testid="presence-chart" role="img" aria-label="Публикации вузов по соцсетям">
      <BarChart data={data} layout="vertical" margin={{ left: 4, right: 12, top: 4 }} barCategoryGap={3}
        onClick={rowPicker(data, onPick)} className={onPick ? "cursor-pointer" : undefined}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tickLine={false} axisLine={false} height={X_TITLE_HEIGHT} label={xTitle("Публикаций за период")} />
        <YAxis type="category" dataKey="name" width={132} tickLine={false} axisLine={false} interval={0}
          tick={(props) => <NameTick {...props} rows={data} highlights={highlights} onPick={onPick} />} />
        <ChartTooltip content={(props) => {
          const item = props.payload?.[0]?.payload as (typeof data)[number] | undefined;
          return <>
            <ChartTooltipContent active={props.active} payload={props.payload} label={props.label}
              valueFormatter={(value) => formatInteger(Number(value))} />
            {onPick && item && props.active ? <div className="text-muted-foreground mt-1 text-xs">{pickNote(highlights, item.id)}</div> : null}
          </>;
        }} />
        {NETWORKS.map((network, index) => (
          <Bar key={network} dataKey={network} stackId="posts" fill={`var(--color-${network})`} isAnimationActive={false} onClick={barPicker(onPick)}
            radius={index === NETWORKS.length - 1 ? [0, 4, 4, 0] : 0} />
        ))}
        <ChartLegend verticalAlign="top" content={<ChartLegendContent />} />
      </BarChart>
    </ChartContainer>
  );
}

/** Охват по дням: линия каждой площадки показывает её собственное значение. */
export function ReachAreaChart({ data, platform }: { data: Dashboard; platform: DashboardPlatform }) {
  const rows = useMemo(() => dailyRows(data), [data]);
  const partial = incompleteDay(data);
  const networks: readonly Network[] = platform === "all" ? NETWORKS : [platform];
  const config = partialConfig(Object.fromEntries(networks.map((network) => [`views_${network}`, { label: PLATFORM_NAMES[network], color: PLATFORM_COLORS[network] }])));
  if (!rows.length) return <EmptyChart />;
  return (
    <ChartContainer config={config} className="aspect-auto h-[300px] w-full" data-testid="reach-chart" role="img"
      aria-label="Просмотры публикаций по дню выхода">
      <LineChart data={rows} margin={{ left: 4, right: 12, top: 14 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="day" tickFormatter={dayLabel} tickLine={false} axisLine={false} minTickGap={16} />
        <YAxis tickFormatter={(value) => formatCompact(value)} tickLine={false} axisLine={false} width={70 + AXIS_TITLE_GUTTER}
          label={yTitle("Просмотры постов дня, сумма")} />
        <ChartTooltip content={(props) => <ChartTooltipContent active={props.active} label={props.label} payload={withoutPartialEchoes(props.payload)}
          labelFormatter={(value) => `${dayLabel(String(value))}${value === partial ? `, ${PARTIAL_LABEL}` : ""}`}
          valueFormatter={(value) => formatInteger(Number(value))} />} />
        {partial ? <ReferenceLine x={partial} stroke="var(--border)" strokeDasharray="2 3">
          <Label value={PARTIAL_LABEL} position="insideTopRight" fontSize={10} fill="var(--muted-foreground)" />
        </ReferenceLine> : null}
        {networks.map((network) => (
          <Line key={network} dataKey={`views_${network}`} type="monotone"
            stroke={`var(--color-views_${network})`} strokeWidth={2} dot={false} isAnimationActive={false} />
        ))}
        {partial ? partialLines(networks.map((network) => ({ key: `views_${network}` }))) : null}
        <ChartLegend content={<ChartLegendContent />} />
      </LineChart>
    </ChartContainer>
  );
}

function EmptyChart({ text = "Недостаточно данных за выбранный период." }: { text?: string }) {
  return <Empty className="h-[200px] rounded-lg border p-0"><EmptyDescription className="text-sm">{text}</EmptyDescription></Empty>;
}
