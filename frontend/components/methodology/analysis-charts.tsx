"use client";

import { useState } from "react";
import {
  Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Label, Line, LineChart, Pie, PieChart, PolarAngleAxis,
  RadialBar, RadialBarChart, ReferenceArea, ReferenceLine, XAxis, YAxis,
} from "recharts";
import {
  ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig,
} from "@/components/ui/chart";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { LEVEL_COLORS, LEVEL_NAMES, PLATFORM_NAMES } from "@/lib/compare-dashboard";
import data from "@/content/methodology/analysis-charts.json";
import type { ChartName } from "@/lib/methodology-charts";

export type { ChartName };


// Цвета метрик — как на графиках поста: реакции зелёные, просмотры синие.
// Ожидание модели — нейтральное, отклонение — янтарное.
const REACTIONS = "var(--chart-1)";
const VIEWS = "var(--chart-2)";
const SIGNAL = "var(--chart-3)";
const MODEL = "var(--muted-foreground)";
const AXIS = { tickLine: false, axisLine: false, fontSize: 11 } as const;
const FRAME = "aspect-auto h-64 w-full";
const number = new Intl.NumberFormat("ru-RU");
const hours = (value: number) => value >= 48 ? `${Math.round(value / 24)} сут` : `${value} ч`;
const percent = (value: number, digits = 1) => `${(value * 100).toFixed(digits).replace(".", ",")} %`;
type Platform = "telegram" | "vk" | "max" | "rutube";

export function AnalysisChart({ chart }: { chart: ChartName }) {
  const Component = CHARTS[chart];
  return <Component />;
}

const CHARTS: Record<ChartName, () => React.JSX.Element> = {
  decay: DecayChart, strengths: StrengthsChart, levels: LevelsChart, families: FamiliesChart, schedule: ScheduleChart,
  "linear-feed": LinearFeedChart, "late-spike": LateSpikeChart, "gap-growth": GapGrowthChart,
  "catch-up": CatchUpChart, "reactions-before-views": ReactionsBeforeViewsChart,
  "reactions-exceed-views": ReactionsExceedViewsChart, "synchronous-rise": SynchronousRiseChart,
  "burst-plateau": BurstPlateauChart, "bounded-burst": BoundedBurstChart, erv: ErvChart,
  "mature-reference": MatureReferenceChart, "late-engagement": LateEngagementChart, "tail-cohort": TailCohortChart,
  "tail-histogram": TailHistogramChart, "tail-statuses": TailStatusesChart, "tail-sensitivity": TailSensitivityChart,
};

function PlatformSwitch({ value, options, onChange }: {
  value: Platform; options: readonly Platform[]; onChange: (value: Platform) => void;
}) {
  return (
    <ToggleGroup size="sm" variant="outline" spacing={0} value={[value]} aria-label="Площадка"
      onValueChange={(next) => { const chosen = next[0] as Platform | undefined; if (chosen) onChange(chosen); }}>
      {options.map((option) => <ToggleGroupItem key={option} value={option}>{PLATFORM_NAMES[option]}</ToggleGroupItem>)}
    </ToggleGroup>
  );
}

function DecayChart() {
  const config = { actual: { label: "просмотры за час", color: VIEWS }, model: { label: "модель a·(t+c)^−b", color: MODEL } } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className={FRAME} role="img" aria-label="Скорость просмотров органического поста и модель затухания">
      <ComposedChart data={data.decay.points} margin={{ left: 4, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        {/* Обе оси логарифмические: степенной закон на них — почти прямая. */}
        <XAxis dataKey="hour" {...AXIS} tickFormatter={hours} ticks={[1, 3, 6, 12, 24, 48]} type="number" scale="log" domain={[1, 72]} />
        <YAxis {...AXIS} width={44} scale="log" domain={[1, 5000]} ticks={[1, 10, 100, 1000]} allowDataOverflow tickFormatter={(value) => number.format(value)} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => hours(Number(payload?.[0]?.payload?.hour))} />} />
        <Area dataKey="actual" type="monotone" stroke={VIEWS} fill={VIEWS} fillOpacity={0.18} strokeWidth={2} isAnimationActive={false} />
        <Line dataKey="model" type="monotone" stroke={MODEL} strokeDasharray="5 4" dot={false} strokeWidth={2} isAnimationActive={false} />
        <ChartLegend content={<ChartLegendContent />} />
      </ComposedChart>
    </ChartContainer>
  );
}

const STRENGTH_EXAMPLES = [
  ["linearFeed", "линейная подача"], ["burstPlateau", "рывок с плато"], ["reactionsBeforeViews", "реакции раньше просмотров"],
  ["lateEngagement", "поздняя вовлечённость"], ["erv", "ERV вне нормы"], ["catchUp", "реакции догоняют просмотры"],
] as const;

function StrengthsChart() {
  const rows = STRENGTH_EXAMPLES.map(([key, name], index) => ({
    name, strength: (data[key] as { sign: { strength: number } }).sign.strength, fill: `var(--chart-${index + 1})`,
  }));
  const config = Object.fromEntries(rows.map((row) => [row.name, { label: row.name, color: row.fill }])) satisfies ChartConfig;
  return (
    <div className="grid items-center gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,14rem)]">
      <ChartContainer config={config} className="mx-auto aspect-square h-64" role="img"
        aria-label={`Сила признаков эталона: ${rows.map((row) => `${row.name} ${row.strength}`).join(", ")}`}>
        <RadialBarChart data={rows} innerRadius="22%" outerRadius="100%" startAngle={90} endAngle={-270} barSize={10}>
          <PolarAngleAxis type="number" domain={[0, 1]} tick={false} />
          <ChartTooltip content={<ChartTooltipContent nameKey="name" hideLabel valueFormatter={(value) => Number(value).toFixed(2)} />} />
          <RadialBar dataKey="strength" background cornerRadius={4} isAnimationActive={false} />
        </RadialBarChart>
      </ChartContainer>
      <ul className="grid gap-1.5 text-xs">
        {rows.map((row) => (
          <li key={row.name} className="flex items-center gap-2">
            <span className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: row.fill }} aria-hidden="true" />
            <span className="text-muted-foreground flex-1">{row.name}</span>
            <span className="font-medium tabular-nums">{row.strength.toFixed(2)}</span>
          </li>
        ))}
        <li className="text-muted-foreground mt-2 border-t pt-2">Пороги: 0,2 — слабый, 0,45 — средний, 0,7 — сильный.</li>
      </ul>
    </div>
  );
}

function LevelsChart() {
  const [platform, setPlatform] = useState<Platform>("vk");
  const counts = [0, 1, 2, 3].map((level) => data.production.levels
    .filter((row) => row.platform === platform && row.level === level).reduce((sum, row) => sum + row.n, 0));
  const total = counts.reduce((sum, value) => sum + value, 0);
  const rows = counts.map((count, level) => ({ level: `level${level}`, count, fill: `var(--color-level${level})` }));
  const config = Object.fromEntries(LEVEL_NAMES.map((name, level) => [`level${level}`, { label: name, color: LEVEL_COLORS[level] }])) satisfies ChartConfig;
  const flagged = total ? (counts[1]! + counts[2]! + counts[3]!) / total : 0;
  return (
    <div className="grid gap-3">
      <PlatformSwitch value={platform} options={["telegram", "vk", "max", "rutube"]} onChange={setPlatform} />
      <div className="grid items-center gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,15rem)]">
        <ChartContainer config={config} className="mx-auto aspect-square h-60" role="img"
          aria-label={`${PLATFORM_NAMES[platform]}: с сигналом ${percent(flagged)} из ${number.format(total)} постов`}>
          <PieChart>
            <ChartTooltip content={<ChartTooltipContent nameKey="level" hideLabel valueFormatter={(value) => number.format(Number(value))} />} />
            <Pie data={rows} dataKey="count" nameKey="level" innerRadius={62} outerRadius={96} strokeWidth={2} isAnimationActive={false}>
              <Label content={({ viewBox }) => {
                if (!viewBox || !("cx" in viewBox)) return null;
                return (
                  <text x={viewBox.cx} y={viewBox.cy} textAnchor="middle" dominantBaseline="middle">
                    <tspan x={viewBox.cx} y={viewBox.cy} className="fill-foreground text-2xl font-bold">{percent(flagged)}</tspan>
                    <tspan x={viewBox.cx} y={(viewBox.cy ?? 0) + 20} className="fill-muted-foreground text-[11px]">с сигналом</tspan>
                  </text>
                );
              }} />
            </Pie>
          </PieChart>
        </ChartContainer>
        <ul className="grid gap-1.5 text-xs">
          {LEVEL_NAMES.map((name, level) => (
            <li key={name} className="flex items-center gap-2">
              <span className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: LEVEL_COLORS[level] }} aria-hidden="true" />
              <span className="text-muted-foreground flex-1">{name}</span>
              <span className="font-medium tabular-nums">{number.format(counts[level]!)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

const FAMILIES = [["velocity", "скорость"], ["shape", "форма"], ["cross_metric", "согласие метрик"], ["synchrony", "синхронность"]] as const;

const FAMILY_COLORS = { velocity: "var(--chart-2)", shape: "var(--chart-3)", cross_metric: "var(--chart-1)", synchrony: "var(--chart-4)" } as const;

function FamiliesChart() {
  const platforms = ["telegram", "vk", "max", "rutube"] as const;
  const rows = platforms.map((platform) => ({
    platform: PLATFORM_NAMES[platform],
    ...Object.fromEntries(FAMILIES.map(([family]) => [family, data.production.signals
      .filter((row) => row.platform === platform && row.family === family).reduce((sum, row) => sum + row.n, 0)])),
  }));
  const config = Object.fromEntries(FAMILIES.map(([family, label]) => [family, { label, color: FAMILY_COLORS[family] }])) satisfies ChartConfig;
  return (
    <ChartContainer config={config} className={FRAME} role="img" aria-label="Доля признаков каждого семейства по площадкам">
      <BarChart data={rows} layout="vertical" stackOffset="expand" margin={{ left: 8, right: 16, top: 8 }}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" {...AXIS} tickFormatter={(value) => `${Math.round(value * 100)} %`} />
        <YAxis type="category" dataKey="platform" {...AXIS} width={84} />
        <ChartTooltip content={<ChartTooltipContent valueFormatter={(value) => `${number.format(Number(value))} признаков`} />} />
        {FAMILIES.map(([family], index) => (
          <Bar key={family} dataKey={family} stackId="family" fill={FAMILY_COLORS[family]} isAnimationActive={false}
            radius={index === FAMILIES.length - 1 ? [0, 4, 4, 0] : 0} />
        ))}
        <ChartLegend content={<ChartLegendContent />} />
      </BarChart>
    </ChartContainer>
  );
}

function ScheduleChart() {
  const [platform, setPlatform] = useState<"telegram" | "rutube">("telegram");
  const rutube = platform === "rutube";
  const rows = data.schedule.points.map((row) => ({ day: row.day, collect: rutube ? row.collectRutube : row.collect,
    analyze: rutube ? row.analyzeRutube : row.analyze }));
  const config = { collect: { label: "шаг сбора", color: VIEWS }, analyze: { label: "шаг анализа", color: SIGNAL } } satisfies ChartConfig;
  const minutes = (value: number) => value >= 60 ? `${Math.round(value / 60)} ч` : `${value} мин`;
  return (
    <div className="grid gap-3">
      <ToggleGroup size="sm" variant="outline" spacing={0} value={[platform]} aria-label="Площадки"
        onValueChange={(next) => { if (next[0] === "telegram" || next[0] === "rutube") setPlatform(next[0]); }}>
        <ToggleGroupItem value="telegram">Telegram, ВКонтакте, MAX</ToggleGroupItem>
        <ToggleGroupItem value="rutube">Rutube</ToggleGroupItem>
      </ToggleGroup>
      <ChartContainer config={config} className={FRAME} role="img" aria-label="Шаг сбора и шаг анализа по возрасту поста">
        <LineChart data={rows} margin={{ left: 4, right: 12, top: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="day" type="number" domain={[0, 30]} ticks={[0, 1, 3, 7, 14, 30]} {...AXIS} tickFormatter={(value) => `${value} сут`} />
          <YAxis scale="log" domain={[4, 1600]} ticks={[5, 15, 60, 180, 720, 1440]} {...AXIS} width={52} tickFormatter={minutes} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => `возраст ${payload?.[0]?.payload?.day} сут`}
            valueFormatter={(value) => minutes(Number(value))} />} />
          <Line dataKey="collect" type="stepAfter" stroke={VIEWS} strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line dataKey="analyze" type="stepAfter" stroke={SIGNAL} strokeWidth={2} dot={false} isAnimationActive={false} />
          <ChartLegend content={<ChartLegendContent />} />
        </LineChart>
      </ChartContainer>
    </div>
  );
}

function LinearFeedChart() {
  const { points, start, end } = data.linearFeed;
  const config = { views: { label: "просмотры, накопленно", color: VIEWS }, fit: { label: "прямая аппроксимации", color: SIGNAL } } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className={FRAME} role="img" aria-label="Накопленные просмотры с участком почти постоянной скорости">
      <LineChart data={points} margin={{ left: 4, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="hour" type="number" domain={[0, 96]} ticks={[0, 24, 48, 72, 96]} {...AXIS} tickFormatter={hours} />
        <YAxis {...AXIS} width={52} tickFormatter={(value) => number.format(value)} />
        <ReferenceArea x1={start} x2={end} fill={SIGNAL} fillOpacity={0.08} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => hours(Number(payload?.[0]?.payload?.hour))}
          valueFormatter={(value) => number.format(Number(value))} />} />
        <Line dataKey="views" stroke={VIEWS} strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line dataKey="fit" stroke={SIGNAL} strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls={false} isAnimationActive={false} />
        <ChartLegend content={<ChartLegendContent />} />
      </LineChart>
    </ChartContainer>
  );
}

function LateSpikeChart() {
  const config = {
    actual: { label: "просмотры, накопленно", color: VIEWS }, model: { label: "ожидание по затуханию", color: MODEL },
    band: { label: "полоса модели ±2σ", color: MODEL },
  } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className={FRAME} role="img" aria-label="Поздний скачок просмотров над ожиданием модели">
      <ComposedChart data={data.lateSpike.points} margin={{ left: 4, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="hour" type="number" domain={[24, 120]} ticks={[24, 48, 72, 96, 120]} {...AXIS} tickFormatter={hours} />
        <YAxis {...AXIS} width={52} tickFormatter={(value) => number.format(value)} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => hours(Number(payload?.[0]?.payload?.hour))}
          valueFormatter={(value) => Array.isArray(value) ? value.map((item) => number.format(Number(item))).join("–") : number.format(Number(value))} />} />
        <Area dataKey="band" stroke="none" fill={MODEL} fillOpacity={0.14} isAnimationActive={false} />
        <Line dataKey="model" stroke={MODEL} strokeDasharray="5 4" strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line dataKey="actual" stroke={VIEWS} strokeWidth={2} dot={false} isAnimationActive={false} />
        <ChartLegend content={<ChartLegendContent />} />
      </ComposedChart>
    </ChartContainer>
  );
}

function GapGrowthChart() {
  const [from, to] = data.gapGrowth.gap as [number, number];
  const config = { views: { label: "просмотры в сохранённых замерах", color: VIEWS } } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className={FRAME} role="img" aria-label="Прирост просмотров между замерами по обе стороны пробела сбора">
      <LineChart data={data.gapGrowth.points} margin={{ left: 4, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="hour" type="number" domain={[36, 96]} ticks={[36, 48, 60, 72, 84, 96]} {...AXIS} tickFormatter={hours} />
        <YAxis {...AXIS} width={52} tickFormatter={(value) => number.format(value)} />
        <ReferenceArea x1={from} x2={to} fill={MODEL} fillOpacity={0.12}>
          <Label value="пробел сбора" position="insideTop" fontSize={11} fill="var(--muted-foreground)" />
        </ReferenceArea>
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => `${Number(payload?.[0]?.payload?.hour).toFixed(1)} ч`}
          valueFormatter={(value) => number.format(Number(value))} />} />
        {/* Точки — настоящие замеры: линия между ними не утверждает форму роста. */}
        <Line dataKey="views" stroke={VIEWS} strokeWidth={2} dot={{ r: 3 }} strokeDasharray="2 4" isAnimationActive={false} />
      </LineChart>
    </ChartContainer>
  );
}

function CatchUpChart() {
  const config = {
    actual: { label: "реакции за 6 ч", color: SIGNAL }, expected: { label: "доля участка × просмотры", color: MODEL },
    band: { label: "пуассоновский коридор ±2√λ", color: MODEL },
  } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className={FRAME} role="img" aria-label="Прирост реакций в окнах по 6 часов против пуассоновского коридора">
      <ComposedChart data={data.catchUp.points} margin={{ left: 4, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="window" {...AXIS} interval={3} />
        <YAxis {...AXIS} width={36} />
        <ChartTooltip content={<ChartTooltipContent
          valueFormatter={(value) => Array.isArray(value) ? value.map((item) => Math.round(Number(item))).join("–") : String(Math.round(Number(value)))} />} />
        <Area dataKey="band" stroke="none" fill={MODEL} fillOpacity={0.14} isAnimationActive={false} />
        <Line dataKey="expected" stroke={MODEL} strokeDasharray="5 4" strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line dataKey="actual" stroke={SIGNAL} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
        <ChartLegend content={<ChartLegendContent />} />
      </ComposedChart>
    </ChartContainer>
  );
}

function ReactionsBeforeViewsChart() {
  const config = { reactions: { label: "реакции за час", color: REACTIONS }, views: { label: "просмотры за час", color: VIEWS } } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className={FRAME} role="img" aria-label="Приросты реакций и просмотров за час, в процентах от своего максимума">
      <LineChart data={data.reactionsBeforeViews.points} margin={{ left: 4, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="hour" type="number" domain={[31, 54]} {...AXIS} tickFormatter={(value) => `${value} ч`} />
        <YAxis domain={[0, 100]} {...AXIS} width={44} tickFormatter={(value) => `${value} %`} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => `${payload?.[0]?.payload?.hour} ч`}
          valueFormatter={(value) => `${Math.round(Number(value))} % максимума`} />} />
        <Line dataKey="views" stroke={VIEWS} strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line dataKey="reactions" stroke={REACTIONS} strokeWidth={2} dot={false} isAnimationActive={false} />
        <ChartLegend content={<ChartLegendContent />} />
      </LineChart>
    </ChartContainer>
  );
}

function ReactionsExceedViewsChart() {
  const config = { views: { label: "просмотры", color: VIEWS }, reactions: { label: "реакции", color: REACTIONS } } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className={FRAME} role="img" aria-label="Накопленные реакции обгоняют просмотры">
      <LineChart data={data.reactionsExceedViews.points} margin={{ left: 4, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="hour" type="number" domain={[20, 44]} {...AXIS} tickFormatter={(value) => `${value} ч`} />
        <YAxis {...AXIS} width={44} tickFormatter={(value) => number.format(value)} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => `${payload?.[0]?.payload?.hour} ч`}
          valueFormatter={(value) => number.format(Number(value))} />} />
        <Line dataKey="views" stroke={VIEWS} strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line dataKey="reactions" stroke={REACTIONS} strokeWidth={2} dot={false} isAnimationActive={false} />
        <ChartLegend content={<ChartLegendContent />} />
      </LineChart>
    </ChartContainer>
  );
}

function SynchronousRiseChart() {
  const config = {
    own: { label: "этот пост", color: SIGNAL }, together: { label: "четыре старых поста вместе", color: REACTIONS },
    quiet: { label: "два других старых поста", color: MODEL },
  } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className={FRAME} role="img" aria-label="Прирост реакций по часам на постах аккаунта вокруг события">
      <BarChart data={data.synchronousRise.points} margin={{ left: 4, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="hour" {...AXIS} tickFormatter={(value) => value === 0 ? "0" : `${value > 0 ? "+" : ""}${value}`} />
        <YAxis {...AXIS} width={44} tickFormatter={(value) => number.format(value)} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => `${payload?.[0]?.payload?.hour} ч от события`}
          valueFormatter={(value) => `+${number.format(Number(value))} реакций`} />} />
        <Bar dataKey="together" stackId="posts" fill={REACTIONS} isAnimationActive={false} />
        <Bar dataKey="own" stackId="posts" fill={SIGNAL} isAnimationActive={false} />
        <Bar dataKey="quiet" stackId="posts" fill={MODEL} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        <ChartLegend content={<ChartLegendContent />} />
      </BarChart>
    </ChartContainer>
  );
}

function BurstPlateauChart() {
  const peak = data.burstPlateau.peak ?? 0;
  const config = { views: { label: "просмотры за час", color: VIEWS } } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className={FRAME} role="img" aria-label="Просмотры за час: рывок и обрыв в плато">
      <BarChart data={data.burstPlateau.points} margin={{ left: 4, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="hour" {...AXIS} tickFormatter={(value) => `${value} ч`} interval={3} />
        <YAxis {...AXIS} width={48} tickFormatter={(value) => number.format(value)} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => `${payload?.[0]?.payload?.hour} ч`}
          valueFormatter={(value) => number.format(Number(value))} />} />
        <ReferenceLine y={peak * 0.05} stroke={SIGNAL} strokeDasharray="4 4">
          <Label value="5 % пика" position="insideTopRight" fontSize={11} fill="var(--muted-foreground)" />
        </ReferenceLine>
        <Bar dataKey="views" fill={VIEWS} radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ChartContainer>
  );
}

// Округлённые счётчики известны диапазоном: «1,2K» — это 1 100–1 300.
// Рисунок условный: сами диапазоны и правило их построения — из статьи.
const BOUNDED_ROWS = [
  { name: "до рывка", low: 1100, high: 1300 },
  { name: "через 1 ч", low: 4400, high: 4600 },
  { name: "через 3 ч", low: 4400, high: 4600 },
];

function BoundedBurstChart() {
  const rows = BOUNDED_ROWS.map((row) => ({ ...row, base: row.low, range: row.high - row.low }));
  const config = { range: { label: "возможные значения", color: REACTIONS } } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className={FRAME} role="img" aria-label="Диапазоны округлённого счётчика реакций до и после рывка">
      <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 16, top: 8 }}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" domain={[0, 5000]} {...AXIS} tickFormatter={(value) => number.format(value)} />
        <YAxis type="category" dataKey="name" {...AXIS} width={76} />
        <ChartTooltip content={<ChartTooltipContent hideIndicator formatter={(_, __, item) =>
          `${number.format(item.payload.low)}–${number.format(item.payload.high)} реакций`} />} />
        <Bar dataKey="base" stackId="range" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="range" stackId="range" fill={REACTIONS} radius={4} isAnimationActive={false} />
        <ReferenceArea x1={1300} x2={4400} fill={SIGNAL} fillOpacity={0.08}>
          <Label value="нижний прирост ≥ 3 100" position="insideTop" fontSize={11} fill="var(--muted-foreground)" />
        </ReferenceArea>
      </BarChart>
    </ChartContainer>
  );
}

function ErvChart() {
  const rows = [
    { name: "этот пост", erv: data.erv.post ?? 0, fill: SIGNAL },
    { name: "медиана нормы аккаунта", erv: data.erv.median ?? 0, fill: MODEL },
  ];
  const config = { erv: { label: "ERV", color: SIGNAL } } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className="aspect-auto h-40 w-full" role="img"
      aria-label={`ERV поста ${percent(rows[0]!.erv)} против медианы ${percent(rows[1]!.erv)}`}>
      <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 48, top: 8 }}>
        <XAxis type="number" hide />
        <YAxis type="category" dataKey="name" {...AXIS} width={148} />
        <ChartTooltip content={<ChartTooltipContent hideLabel valueFormatter={(value) => percent(Number(value))} />} />
        <Bar dataKey="erv" radius={4} isAnimationActive={false}
          label={{ position: "right", fontSize: 11, formatter: (value: unknown) => percent(Number(value)) }}>
          {rows.map((row) => <Cell key={row.name} fill={row.fill} />)}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}

function MatureReferenceChart() {
  const reference = data.matureReference;
  const panels = (["views", "reactions"] as const).map((metric) => ({
    metric,
    rows: reference.rows.filter((row) => row.metric === metric).map((row) => ({
      name: row.conditional ? "с учётом первых суток" : "по истории аккаунта", expected: row.expected, upper: row.upper,
    })),
  }));
  const config = { expected: { label: "ожидание к 72 ч", color: MODEL }, upper: { label: "верхняя граница", color: SIGNAL } } satisfies ChartConfig;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {panels.map((panel) => (
        <div key={panel.metric} className="grid gap-1">
          <p className="text-muted-foreground text-xs">{panel.metric === "views" ? `Просмотры (в первые сутки ${number.format(reference.early.views)})` : `Реакции (в первые сутки ${reference.early.reactions})`}</p>
          <ChartContainer config={config} className="aspect-auto h-52 w-full" role="img"
            aria-label={`${panel.metric === "views" ? "Просмотры" : "Реакции"}: ожидание и граница к 72 часам`}>
            <BarChart data={panel.rows} margin={{ left: 4, right: 8, top: 16 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="name" {...AXIS} />
              <YAxis {...AXIS} width={44} tickFormatter={(value) => number.format(value)} />
              <ChartTooltip content={<ChartTooltipContent valueFormatter={(value) => number.format(Number(value))} />} />
              <Bar dataKey="expected" fill={MODEL} radius={[4, 4, 0, 0]} isAnimationActive={false} />
              <Bar dataKey="upper" fill={SIGNAL} radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ChartContainer>
        </div>
      ))}
    </div>
  );
}

function LateEngagementChart() {
  const late = data.lateEngagement;
  const rows = [
    { name: "первые сутки", rate: late.earlyRate, fill: MODEL },
    { name: "просмотры после 4 суток", rate: late.lateRate, fill: SIGNAL },
  ];
  const config = { rate: { label: "реакций на просмотр", color: SIGNAL } } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className="aspect-auto h-40 w-full" role="img"
      aria-label={`Доля реакций: первые сутки ${percent(late.earlyRate)}, после четырёх суток ${percent(late.lateRate)}`}>
      <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 56, top: 8 }}>
        <XAxis type="number" hide />
        <YAxis type="category" dataKey="name" {...AXIS} width={160} />
        <ChartTooltip content={<ChartTooltipContent hideLabel valueFormatter={(value) => percent(Number(value))} />} />
        <Bar dataKey="rate" radius={4} isAnimationActive={false}
          label={{ position: "right", fontSize: 11, formatter: (value: unknown) => percent(Number(value)) }}>
          {rows.map((row) => <Cell key={row.name} fill={row.fill} />)}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}

const TAIL_PLATFORMS = ["telegram", "vk", "max"] as const;
type TailPlatform = (typeof TAIL_PLATFORMS)[number];
const tailPlatforms = data.tail.platforms as Record<string, {
  accounts: number; statuses: Record<string, number>;
  cohort: { median: number; p90: number; threshold: number } | null;
  histogram?: { bin: string; from: number; accounts: number }[];
}>;

function TailCohortChart() {
  const rows = TAIL_PLATFORMS.map((platform) => ({ platform: PLATFORM_NAMES[platform], ...tailPlatforms[platform]!.cohort }));
  const config = {
    median: { label: "медиана K", color: MODEL }, p90: { label: "90-й перцентиль", color: VIEWS },
    threshold: { label: "порог «необычный»", color: SIGNAL },
  } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className={FRAME} role="img" aria-label="Медиана, 90-й перцентиль и порог отношения K по площадкам">
      <BarChart data={rows} margin={{ left: 4, right: 8, top: 16 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="platform" {...AXIS} />
        <YAxis {...AXIS} width={36} tickFormatter={(value) => String(value).replace(".", ",")} />
        <ReferenceLine y={1} stroke="var(--border)">
          <Label value="K = 1" position="insideTopRight" fontSize={11} fill="var(--muted-foreground)" />
        </ReferenceLine>
        <ChartTooltip content={<ChartTooltipContent valueFormatter={(value) => Number(value).toFixed(2).replace(".", ",")} />} />
        <Bar dataKey="median" fill={MODEL} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        <Bar dataKey="p90" fill={VIEWS} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        <Bar dataKey="threshold" fill={SIGNAL} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        <ChartLegend content={<ChartLegendContent />} />
      </BarChart>
    </ChartContainer>
  );
}

function TailHistogramChart() {
  const [platform, setPlatform] = useState<TailPlatform>("max");
  const entry = tailPlatforms[platform]!;
  const threshold = entry.cohort?.threshold ?? 0;
  const rows = (entry.histogram ?? []).map((row) => ({ ...row, label: row.bin.replace(/\./g, ","),
    fill: row.from >= threshold || (row.from < threshold && Number(row.bin.split("–")[1]) > threshold) ? SIGNAL : MODEL }));
  const config = { accounts: { label: "аккаунтов", color: MODEL } } satisfies ChartConfig;
  return (
    <div className="grid gap-3">
      <PlatformSwitch value={platform} options={TAIL_PLATFORMS} onChange={(value) => setPlatform(value as TailPlatform)} />
      <ChartContainer config={config} className={FRAME} role="img" aria-label={`${PLATFORM_NAMES[platform]}: распределение аккаунтов по K`}>
        <BarChart data={rows} margin={{ left: 4, right: 8, top: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="label" {...AXIS} interval={0} angle={-35} textAnchor="end" height={48} />
          <YAxis {...AXIS} width={28} allowDecimals={false} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => `K ${payload?.[0]?.payload?.label}`} />} />
          <Bar dataKey="accounts" radius={[4, 4, 0, 0]} isAnimationActive={false}>
            {rows.map((row) => <Cell key={row.bin} fill={row.fill} />)}
          </Bar>
        </BarChart>
      </ChartContainer>
    </div>
  );
}

const STATUS_KEYS = [
  ["0", "обычный", "var(--muted-foreground)"], ["1", "необычный", "var(--chart-10)"],
  ["2", "устойчиво необычный", "var(--chart-3)"], ["abstain", "недостаточно данных", "var(--border)"],
] as const;

function TailStatusesChart() {
  const rows = (["telegram", "vk", "max", "rutube"] as const).map((platform) => {
    const statuses = tailPlatforms[platform]!.statuses;
    const abstain = Object.entries(statuses).filter(([key]) => key.startsWith("abstain")).reduce((sum, [, value]) => sum + value, 0);
    return { platform: PLATFORM_NAMES[platform], "0": statuses["0"] ?? 0, "1": statuses["1"] ?? 0, "2": statuses["2"] ?? 0, abstain };
  });
  const config = Object.fromEntries(STATUS_KEYS.map(([key, label, color]) => [key, { label, color }])) satisfies ChartConfig;
  return (
    <ChartContainer config={config} className={FRAME} role="img" aria-label="Статусы профиля позднего отклика по площадкам">
      <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 16, top: 8 }}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" {...AXIS} allowDecimals={false} />
        <YAxis type="category" dataKey="platform" {...AXIS} width={84} />
        <ChartTooltip content={<ChartTooltipContent valueFormatter={(value) => `${value} акк.`} />} />
        {STATUS_KEYS.map(([key, , color], index) => (
          <Bar key={key} dataKey={key} stackId="status" fill={color} isAnimationActive={false}
            radius={index === STATUS_KEYS.length - 1 ? [0, 4, 4, 0] : 0} />
        ))}
        <ChartLegend content={<ChartLegendContent />} />
      </BarChart>
    </ChartContainer>
  );
}

const DOSES = [["daily_2", "+1/сут, до 2"], ["daily_3", "до 3"], ["daily_5", "до 5"], ["daily_10", "до 10"], ["session_once", "сессия читателя"]] as const;

function TailSensitivityChart() {
  const [platform, setPlatform] = useState<TailPlatform>("max");
  const entry = (data.tail.sensitivity as Record<string, Record<string, Record<string, number> | number>>)[platform]!;
  const rows = DOSES.map(([key, label]) => {
    const outcome = entry[key] as Record<string, number>;
    return { dose: label, "0": outcome["0"] ?? 0, "1": outcome["1"] ?? 0, "2": outcome["2"] ?? 0 };
  });
  const config = Object.fromEntries(STATUS_KEYS.slice(0, 3).map(([key, label, color]) => [key, { label, color }])) satisfies ChartConfig;
  return (
    <div className="grid gap-3">
      <PlatformSwitch value={platform} options={TAIL_PLATFORMS} onChange={(value) => setPlatform(value as TailPlatform)} />
      <ChartContainer config={config} className={FRAME} role="img" aria-label={`${PLATFORM_NAMES[platform]}: статус 20 обычных аккаунтов после добавки`}>
        <BarChart data={rows} margin={{ left: 4, right: 8, top: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="dose" {...AXIS} />
          <YAxis domain={[0, 20]} {...AXIS} width={28} allowDecimals={false} />
          <ChartTooltip content={<ChartTooltipContent valueFormatter={(value) => `${value} из 20`} />} />
          {STATUS_KEYS.slice(0, 3).map(([key, , color], index) => (
            <Bar key={key} dataKey={key} stackId="status" fill={color} isAnimationActive={false} radius={index === 2 ? [4, 4, 0, 0] : 0} />
          ))}
          <ChartLegend content={<ChartLegendContent />} />
        </BarChart>
      </ChartContainer>
    </div>
  );
}
