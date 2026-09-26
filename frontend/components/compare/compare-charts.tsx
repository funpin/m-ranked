"use client";

import { useMemo } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Label, Line, LineChart, Pie, PieChart,
  PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ReferenceLine, Scatter, ScatterChart,
  XAxis, YAxis, ZAxis,
} from "recharts";
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import {
  LEVEL_COLORS, LEVEL_NAMES, METRICS, NETWORKS, PLATFORM_COLORS, PLATFORM_NAMES,
  curveRows, dailyRows, formatCompact, formatInteger, formatPercent, formatValue, hourlyReach, levelSharesByPlatform,
  median, metricValue, percentileRank, sortRows, typeRows,
  type Dashboard, type DashboardPlatform, type InstitutionRow, type Metric, type Network,
} from "@/lib/compare-dashboard";

/** Выделенные вузы: id → цвет. Остальные рисуются нейтрально. */
export type Highlights = ReadonlyMap<string, string>;

const BASE_BAR = "var(--chart-2)";
const MUTED_BAR = "color-mix(in oklch, var(--chart-2) 45%, transparent)";
const dayLabel = (value: string) => {
  const [, month, day] = value.split("-");
  return `${Number(day)}.${month}`;
};

function TooltipBox({ title, lines }: { title: string; lines: [string, string][] }) {
  return (
    <div className="border-border/50 bg-background grid min-w-40 gap-1 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl">
      <div className="font-medium">{title}</div>
      {lines.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-4">
          <span className="text-muted-foreground">{label}</span>
          <span className="text-foreground font-mono font-medium tabular-nums">{value}</span>
        </div>
      ))}
    </div>
  );
}

/** Рейтинг всех вузов по одной мере: горизонтальные полосы, высота растёт с
 *  числом вузов, поэтому ограничения на их число нет. Пунктир — медиана. */
export function RankingChart({ rows, metric, highlights, descending = true }: {
  rows: readonly InstitutionRow[]; metric: Metric; highlights: Highlights; descending?: boolean;
}) {
  const data = useMemo(() => sortRows(rows, metric, descending)
    .filter((row) => metricValue(row, metric) !== null)
    .map((row) => ({ id: row.id, name: row.name, value: metricValue(row, metric)!, row })), [rows, metric, descending]);
  const middle = median(data.map((item) => item.value));
  const config = { value: { label: METRICS[metric].short, color: BASE_BAR } } satisfies ChartConfig;
  if (!data.length) return <EmptyChart />;
  const anyHighlight = highlights.size > 0;
  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height: Math.max(220, data.length * 22 + 48) }}
      data-testid="ranking-chart" role="img" aria-label={`Рейтинг вузов: ${METRICS[metric].label}`}>
      <BarChart data={data} layout="vertical" margin={{ left: 4, right: 48, top: 22, bottom: 8 }} barCategoryGap={3}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tickFormatter={(value) => formatValue(value, metric)} tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey="name" width={132} tickLine={false} axisLine={false} interval={0}
          tick={{ fontSize: 11 }} tickFormatter={(value: string) => (value.length > 20 ? `${value.slice(0, 19)}…` : value)} />
        <ChartTooltip cursor={{ fillOpacity: 0.4 }} content={({ active, payload }) => {
          const item = active ? payload?.[0]?.payload as (typeof data)[number] | undefined : undefined;
          if (!item) return null;
          return <TooltipBox title={item.row.fullName} lines={[
            [METRICS[metric].short, formatValue(item.value, metric)],
            ["Публикаций", formatInteger(item.row.posts)],
            ["Проанализировано", formatInteger(item.row.analyzed)],
          ]} />;
        }} />
        {middle !== null ? (
          <ReferenceLine x={middle} stroke="var(--foreground)" strokeOpacity={0.5} strokeDasharray="4 4">
            <Label value={`медиана ${formatValue(middle, metric)}`} position="top" fontSize={10} fill="var(--muted-foreground)" />
          </ReferenceLine>
        ) : null}
        <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false}
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
export function ScatterMap({ rows, x, y, highlights }: {
  rows: readonly InstitutionRow[]; x: Metric; y: Metric; highlights: Highlights;
}) {
  const points = useMemo(() => rows
    .map((row) => ({ id: row.id, name: row.fullName, short: row.name, x: metricValue(row, x), y: metricValue(row, y), z: Math.max(row.subscribers, 1) }))
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
      <ScatterChart margin={{ left: 4, right: 16, top: 12, bottom: 20 }}>
        <CartesianGrid />
        <XAxis type="number" dataKey="x" scale="log" domain={["auto", "auto"]} tickFormatter={(value) => formatValue(value, x)} tickLine={false}>
          <Label value={METRICS[x].short} position="insideBottom" offset={-12} fontSize={11} fill="var(--muted-foreground)" />
        </XAxis>
        <YAxis type="number" dataKey="y" scale="log" domain={["auto", "auto"]} tickFormatter={(value) => formatValue(value, y)} tickLine={false} width={56} />
        <ZAxis type="number" dataKey="z" range={[30, 420]} scale="sqrt" />
        {midX !== null ? <ReferenceLine x={midX} stroke="var(--border)" strokeDasharray="4 4" /> : null}
        {midY !== null ? <ReferenceLine y={midY} stroke="var(--border)" strokeDasharray="4 4" /> : null}
        <ChartTooltip cursor={false} content={({ active, payload }) => {
          const point = active ? payload?.[0]?.payload as (typeof points)[number] | undefined : undefined;
          if (!point) return null;
          return <TooltipBox title={point.name} lines={[
            [METRICS[x].short, formatValue(point.x, x)], [METRICS[y].short, formatValue(point.y, y)],
            ["Подписчики", formatCompact(point.z)],
          ]} />;
        }} />
        <Scatter data={points} isAnimationActive={false}>
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

/** Как набираются просмотры: медиана всех вузов площадки — жирная линия,
 *  выделенные — цветом, остальные — тонкий фон, чтобы видеть разброс. */
export function CurvesChart({ data, platform, rows, highlights, field }: {
  data: Dashboard; platform: Network; rows: readonly InstitutionRow[]; highlights: Highlights; field: "views" | "reactions";
}) {
  const ids = useMemo(() => rows.map((row) => row.id), [rows]);
  const chart = useMemo(() => curveRows(data, platform, ids, field), [data, platform, ids, field]);
  const names = new Map(rows.map((row) => [row.id, row.name]));
  const config: ChartConfig = { median: { label: `Медиана ${PLATFORM_NAMES[platform]}`, color: "var(--foreground)" } };
  for (const [id, color] of highlights) config[id] = { label: names.get(id) ?? id, color };
  if (!chart.some((point) => point.median !== null)) return <EmptyChart />;
  return (
    <ChartContainer config={config} className="aspect-auto h-[340px] w-full" data-testid="curves-chart" role="img"
      aria-label="Накопление по часам после публикации">
      <LineChart data={chart} margin={{ left: 4, right: 16, top: 8, bottom: 4 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="hour" tickLine={false} axisLine={false} />
        <YAxis tickFormatter={(value) => formatCompact(value)} tickLine={false} axisLine={false} width={52} />
        <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
        {ids.filter((id) => !highlights.has(id)).map((id) => (
          <Line key={id} dataKey={id} stroke="var(--muted-foreground)" strokeOpacity={0.14} strokeWidth={1}
            dot={false} activeDot={false} isAnimationActive={false} connectNulls tooltipType="none" legendType="none" />
        ))}
        <Line dataKey="median" stroke="var(--color-median)" strokeWidth={3} dot={{ r: 3 }} isAnimationActive={false} connectNulls />
        {[...highlights.keys()].filter((id) => ids.includes(id)).map((id) => (
          <Line key={id} dataKey={id} stroke={`var(--color-${id})`} strokeWidth={2.25} dot={{ r: 2.5 }} isAnimationActive={false} connectNulls />
        ))}
        <ChartLegend content={<ChartLegendContent />} />
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
export function LevelsByPlatform({ data }: { data: Dashboard }) {
  const rows = useMemo(() => levelSharesByPlatform(data), [data]);
  const config = Object.fromEntries(LEVEL_NAMES.map((name, level) => [`level${level}`, { label: name, color: LEVEL_COLORS[level] }])) satisfies ChartConfig;
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

/** Динамика по дням: публикации по площадкам и доля аномалий поверх. */
export function DailyChart({ data, platform }: { data: Dashboard; platform: DashboardPlatform }) {
  const rows = useMemo(() => dailyRows(data), [data]);
  const networks: readonly Network[] = platform === "all" ? NETWORKS : [platform];
  const config: ChartConfig = { [`anomaly_${platform}`]: { label: "Доля аномалий", color: "var(--destructive)" } };
  for (const network of networks) config[`posts_${network}`] = { label: PLATFORM_NAMES[network], color: PLATFORM_COLORS[network] };
  if (!rows.length) return <EmptyChart />;
  return (
    <ChartContainer config={config} className="aspect-auto h-[300px] w-full" data-testid="daily-chart" role="img"
      aria-label="Публикации и доля аномалий по дням">
      <ComposedChart data={rows} margin={{ left: 4, right: 4, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="day" tickFormatter={dayLabel} tickLine={false} axisLine={false} minTickGap={16} />
        <YAxis yAxisId="posts" tickLine={false} axisLine={false} width={40} />
        <YAxis yAxisId="share" orientation="right" tickFormatter={(value) => `${value}%`} tickLine={false} axisLine={false} width={40} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(value) => dayLabel(String(value))}
          valueFormatter={(value, name) => String(name).startsWith("anomaly") ? formatPercent(Number(value)) : formatInteger(Number(value))} />} />
        {networks.map((network) => (
          <Area key={network} yAxisId="posts" dataKey={`posts_${network}`} stackId="posts" type="monotone"
            fill={`var(--color-posts_${network})`} fillOpacity={0.35} stroke={`var(--color-posts_${network})`} isAnimationActive={false} />
        ))}
        <Line yAxisId="share" dataKey={`anomaly_${platform}`} stroke={`var(--color-anomaly_${platform})`} strokeWidth={2}
          dot={false} type="monotone" connectNulls isAnimationActive={false} />
        <ChartLegend content={<ChartLegendContent />} />
      </ComposedChart>
    </ChartContainer>
  );
}

/** Час выхода: сколько публикуют и сколько типичный пост набирает за сутки. */
export function HourlyReachChart({ data, platform }: { data: Dashboard; platform: DashboardPlatform }) {
  const rows = useMemo(() => hourlyReach(data, platform), [data, platform]);
  const config = {
    posts: { label: "Публикаций", color: "var(--chart-9)" },
    views24: { label: "Просмотры за 24 ч, медиана", color: "var(--chart-3)" },
  } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className="aspect-auto h-[280px] w-full" data-testid="hourly-chart" role="img"
      aria-label="Публикации и охват по часу выхода">
      <ComposedChart data={rows} margin={{ left: 4, right: 4, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="hour" tickLine={false} axisLine={false} interval={2} />
        <YAxis yAxisId="posts" tickLine={false} axisLine={false} width={40} />
        <YAxis yAxisId="views" orientation="right" tickFormatter={(value) => formatCompact(value)} tickLine={false} axisLine={false} width={48} />
        <ChartTooltip content={<ChartTooltipContent valueFormatter={(value) => formatInteger(Number(value))} />} />
        <Bar yAxisId="posts" dataKey="posts" fill="var(--color-posts)" fillOpacity={0.55} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        <Line yAxisId="views" dataKey="views24" stroke="var(--color-views24)" strokeWidth={2.25} dot={false} type="monotone" connectNulls isAnimationActive={false} />
        <ChartLegend content={<ChartLegendContent />} />
      </ComposedChart>
    </ChartContainer>
  );
}

/** Форматы публикаций: сколько их и как они работают. */
export function TypesChart({ data, platform }: { data: Dashboard; platform: DashboardPlatform }) {
  const rows = useMemo(() => typeRows(data, platform), [data, platform]);
  const config = {
    posts: { label: "Публикаций", color: "var(--chart-5)" },
    views24: { label: "Просмотры за 24 ч, медиана", color: "var(--chart-11)" },
  } satisfies ChartConfig;
  if (!rows.length) return <EmptyChart />;
  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height: Math.max(200, rows.length * 44 + 60) }}
      data-testid="types-chart" role="img" aria-label="Форматы публикаций">
      <BarChart data={rows} layout="vertical" margin={{ left: 4, right: 40 }} barGap={2}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" xAxisId="posts" hide />
        <XAxis type="number" xAxisId="views" hide />
        <YAxis type="category" dataKey="type" width={80} tickLine={false} axisLine={false} />
        <ChartTooltip content={({ active, payload }) => {
          const item = active ? payload?.[0]?.payload as (typeof rows)[number] | undefined : undefined;
          if (!item) return null;
          return <TooltipBox title={item.type} lines={[
            ["Публикаций", formatInteger(item.posts)], ["Просмотры за 24 ч", formatInteger(item.views24)],
            ["Вовлечённость", formatPercent(item.engagement24)],
          ]} />;
        }} />
        <Bar xAxisId="posts" dataKey="posts" fill="var(--color-posts)" radius={4} isAnimationActive={false}
          label={{ position: "right", fontSize: 10, fill: "var(--muted-foreground)", formatter: (value: unknown) => formatInteger(value as number) }} />
        <Bar xAxisId="views" dataKey="views24" fill="var(--color-views24)" radius={4} isAnimationActive={false}
          label={{ position: "right", fontSize: 10, fill: "var(--muted-foreground)", formatter: (value: unknown) => formatCompact(value as number) }} />
        <ChartLegend content={<ChartLegendContent />} />
      </BarChart>
    </ChartContainer>
  );
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
export function RadarProfile({ rows, highlights }: { rows: readonly InstitutionRow[]; highlights: Highlights }) {
  const chosen = rows.filter((row) => highlights.has(row.id));
  const data = RADAR_AXES.map((axis) => {
    const point: Record<string, string | number | null> = { axis: axis.label };
    for (const row of chosen) point[row.id] = percentileRank(rows, row, axis.metric, axis.inverse);
    return point;
  });
  const config: ChartConfig = {};
  for (const row of chosen) config[row.id] = { label: row.name, color: highlights.get(row.id)! };
  if (!chosen.length) return <EmptyChart text="Выделите вузы, чтобы сравнить их профили." />;
  return (
    <ChartContainer config={config} className="mx-auto aspect-square max-h-[360px] w-full" data-testid="radar-chart" role="img"
      aria-label="Профиль выделенных вузов">
      <RadarChart data={data} outerRadius="72%">
        <ChartTooltip content={<ChartTooltipContent valueFormatter={(value) => `${value} из 100`} />} />
        <PolarGrid />
        <PolarAngleAxis dataKey="axis" tick={{ fontSize: 11 }} />
        <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
        {chosen.map((row) => (
          <Radar key={row.id} dataKey={row.id} stroke={`var(--color-${row.id})`} fill={`var(--color-${row.id})`}
            fillOpacity={chosen.length > 2 ? 0.08 : 0.2} strokeWidth={2} isAnimationActive={false} />
        ))}
        <ChartLegend content={<ChartLegendContent />} />
      </RadarChart>
    </ChartContainer>
  );
}

/** Присутствие в соцсетях: публикации вуза по площадкам, все вузы. */
export function PresenceChart({ rows, highlights }: { rows: readonly InstitutionRow[]; highlights: Highlights }) {
  const data = useMemo(() => [...rows]
    .filter((row) => row.posts > 0)
    .sort((left, right) => right.posts - left.posts)
    .map((row) => ({ id: row.id, name: row.name, fullName: row.fullName, ...row.byNetwork })), [rows]);
  const config = Object.fromEntries(NETWORKS.map((network) => [network, { label: PLATFORM_NAMES[network], color: PLATFORM_COLORS[network] }])) satisfies ChartConfig;
  if (!data.length) return <EmptyChart />;
  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height: data.length * 20 + 72 }}
      data-testid="presence-chart" role="img" aria-label="Публикации вузов по соцсетям">
      <BarChart data={data} layout="vertical" margin={{ left: 4, right: 12, top: 4 }} barCategoryGap={3}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey="name" width={132} tickLine={false} axisLine={false} interval={0}
          tick={({ x, y, payload }) => {
            const item = data.find((row) => row.name === payload.value);
            const color = item ? highlights.get(item.id) : undefined;
            const text = String(payload.value);
            return <text x={x} y={y} dy={4} textAnchor="end" fontSize={11} fontWeight={color ? 700 : 400}
              fill={color ?? "var(--muted-foreground)"}>{text.length > 20 ? `${text.slice(0, 19)}…` : text}</text>;
          }} />
        <ChartTooltip content={<ChartTooltipContent valueFormatter={(value) => formatInteger(Number(value))} />} />
        {NETWORKS.map((network, index) => (
          <Bar key={network} dataKey={network} stackId="posts" fill={`var(--color-${network})`} isAnimationActive={false}
            radius={index === NETWORKS.length - 1 ? [0, 4, 4, 0] : 0} />
        ))}
        <ChartLegend verticalAlign="top" content={<ChartLegendContent />} />
      </BarChart>
    </ChartContainer>
  );
}

/** Охват по дням по площадкам — сколько просмотров набрали вышедшие в этот день посты. */
export function ReachAreaChart({ data, platform }: { data: Dashboard; platform: DashboardPlatform }) {
  const rows = useMemo(() => dailyRows(data), [data]);
  const networks: readonly Network[] = platform === "all" ? NETWORKS : [platform];
  const config = Object.fromEntries(networks.map((network) => [`views_${network}`, { label: PLATFORM_NAMES[network], color: PLATFORM_COLORS[network] }])) satisfies ChartConfig;
  if (!rows.length) return <EmptyChart />;
  return (
    <ChartContainer config={config} className="aspect-auto h-[300px] w-full" data-testid="reach-chart" role="img"
      aria-label="Просмотры публикаций по дню выхода">
      <AreaChart data={rows} margin={{ left: 4, right: 12, top: 8 }}>
        <defs>
          {networks.map((network) => (
            <linearGradient key={network} id={`reach-${network}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={`var(--color-views_${network})`} stopOpacity={0.7} />
              <stop offset="95%" stopColor={`var(--color-views_${network})`} stopOpacity={0.05} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="day" tickFormatter={dayLabel} tickLine={false} axisLine={false} minTickGap={16} />
        <YAxis tickFormatter={(value) => formatCompact(value)} tickLine={false} axisLine={false} width={48} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(value) => dayLabel(String(value))}
          valueFormatter={(value) => formatInteger(Number(value))} />} />
        {networks.map((network) => (
          <Area key={network} dataKey={`views_${network}`} stackId="views" type="monotone"
            fill={`url(#reach-${network})`} stroke={`var(--color-views_${network})`} isAnimationActive={false} />
        ))}
        <ChartLegend content={<ChartLegendContent />} />
      </AreaChart>
    </ChartContainer>
  );
}

function EmptyChart({ text = "Недостаточно данных за выбранный период." }: { text?: string }) {
  return <div className="text-muted-foreground flex h-[200px] items-center justify-center rounded-lg border border-dashed text-sm">{text}</div>;
}
