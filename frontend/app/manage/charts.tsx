"use client";

import { Area, AreaChart, Bar, BarChart, CartesianGrid, ComposedChart, Line, LineChart, XAxis, YAxis } from "recharts";
import {
  ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig,
} from "@/components/ui/chart";
import type { ServerPoint, SystemLivePoint, SystemPoint, Visitors } from "@/lib/catalog-api";
import { useLiveHost } from "./live-host";

const AXIS = { tickLine: false, axisLine: false, fontSize: 11 } as const;
const FRAME = "aspect-auto h-56 w-full";
const MOSCOW = "Europe/Moscow";
const dayLabel = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", timeZone: "UTC" });
const weekday = new Intl.DateTimeFormat("ru-RU", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
const hourLabel = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", timeZone: MOSCOW });
const stampLabel = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: MOSCOW });
const number = new Intl.NumberFormat("ru-RU");

/** Уникальные посетители и просмотры по суткам. */
export function VisitorsChart({ days }: { days: Visitors["days"] }) {
  const config = {
    visitors: { label: "посетители", color: "var(--chart-2)" },
    views: { label: "просмотры", color: "var(--chart-1)" },
  } satisfies ChartConfig;
  const data = days.map((day) => ({ ...day, label: dayLabel.format(new Date(`${day.day}T00:00:00Z`)) }));
  return (
    <ChartContainer config={config} className="aspect-auto h-72 w-full">
      <ComposedChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="label" {...AXIS} minTickGap={16} />
        <YAxis {...AXIS} width={40} allowDecimals={false} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => {
          const day = payload?.[0]?.payload?.day as string | undefined;
          return day ? weekday.format(new Date(`${day}T00:00:00Z`)) : "";
        }} />} />
        <ChartLegend content={<ChartLegendContent />} />
        <Bar isAnimationActive={false} dataKey="views" fill="var(--color-views)" fillOpacity={0.35} radius={[4, 4, 0, 0]} maxBarSize={36} />
        <Line isAnimationActive={false} dataKey="visitors" type="monotone" stroke="var(--color-visitors)" strokeWidth={2} dot={{ r: 2.5 }} />
      </ComposedChart>
    </ChartContainer>
  );
}

type Range = "1h" | "3h" | "day" | "week";
const SPAN_MS: Record<Range, number> = { "1h": 3600_000, "3h": 3 * 3600_000, day: 86400_000, week: 7 * 86400_000 };

function prepare<T extends { at: string }>(points: T[], range: Range) {
  return points.map((point) => ({
    ...point,
    label: range === "week" ? dayLabel.format(new Date(point.at)) : hourLabel.format(new Date(point.at)),
    stamp: stampLabel.format(new Date(point.at)),
  }));
}

const secondLabel = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: MOSCOW });

/** Ресурсы для часовых масштабов: живые точки сервера (буфер API — шаг в
 *  секунды, агент сборщика — минута), а то, что старше них, — по ряду периода.
 *  Пропуск замеров — разрыв линии, а не прямая через него. */
function liveResources(points: ServerPoint[], live: SystemLivePoint[], range: Range, step: number) {
  const edge = Date.now() - SPAN_MS[range];
  const fresh = live.filter((point) => Date.parse(point.at) >= edge);
  const start = fresh.length ? Date.parse(fresh[0].at) : Infinity;
  const older = points.filter((point) => Date.parse(point.at) >= edge && Date.parse(point.at) < start);
  const merged: Record<string, string | number | null>[] = [];
  let previous = 0;
  for (const point of [...older, ...fresh]) {
    const at = Date.parse(point.at);
    if (previous && at - previous > Math.max(150_000, 2.5 * step * 1000))
      merged.push({ at: new Date(previous + 1000).toISOString(), label: "", stamp: "нет замеров", cpu: null, memory: null });
    previous = at;
    merged.push({ ...point, label: (range === "week" ? dayLabel : hourLabel).format(new Date(point.at)),
      stamp: (step < 60 ? secondLabel : stampLabel).format(new Date(point.at)) });
  }
  return merged;
}

function tooltip(format?: (value: number) => string) {
  return <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => String(payload?.[0]?.payload?.stamp ?? "")}
    valueFormatter={format ? (value) => format(Number(value)) : undefined} />} />;
}

function Frame({ title, hint, children, wide = false }: { title: string; hint: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <figure className={`min-w-0 rounded-lg border p-4 ${wide ? "lg:col-span-2" : ""}`}>
      <figcaption className="mb-3">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-muted-foreground text-xs">{hint}</p>
      </figcaption>
      {children}
    </figure>
  );
}

function rate(value: number) {
  let unit = 0, n = value;
  while (n >= 1024 && unit < 3) { n /= 1024; unit++; }
  return `${unit ? n.toFixed(1) : Math.round(n)} ${["Б", "КБ", "МБ", "ГБ"][unit]}/с`;
}

/** Ресурсы сервера: CPU и RAM, сеть, диск. Две величины разного масштаба
 *  никогда не делят одну ось: у каждой свой график. Сеть и диск рисуются,
 *  только когда сервер их меряет (у основного — живой буфер часовых масштабов). */
export function ResourceCharts({ points, range, step }: { points: ServerPoint[]; range: Range; step: number }) {
  const live = useLiveHost();
  const hourly = range === "1h" || range === "3h";
  // Сутки и неделя — корзины ряда; пустая корзина тоже рвёт линию.
  const data = liveResources(points, hourly ? live.points : [], range, hourly ? step : range === "week" ? 3600 : 300);
  const resources = {
    cpu: { label: "CPU, %", color: "var(--chart-2)" },
    memory: { label: "RAM, %", color: "var(--chart-4)" },
  } satisfies ChartConfig;
  const network = {
    netTxBytesPerSecond: { label: "отдано", color: "var(--chart-1)" },
    netRxBytesPerSecond: { label: "получено", color: "var(--chart-9)" },
  } satisfies ChartConfig;
  const io = {
    diskWriteBytesPerSecond: { label: "запись", color: "var(--chart-3)" },
    diskReadBytesPerSecond: { label: "чтение", color: "var(--chart-5)" },
  } satisfies ChartConfig;
  const has = (key: string) => data.some((point) => point[key] != null);
  const axis = <XAxis dataKey="label" {...AXIS} minTickGap={range === "week" ? 24 : 32} />;
  const pointsHint = hourly
    ? step < 60 ? `Живые точки каждые ${step} с; старше буфера API — минутные снимки` : "Минутные точки агента сервера"
    : range === "week" ? "Средние за час" : "Средние за пять минут";
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Frame wide title="CPU и RAM" hint={`${pointsHint}. Разрыв линии — пропуск замеров.`}>
        <ChartContainer config={resources} className={FRAME}>
          <AreaChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} />
            {axis}
            <YAxis {...AXIS} width={36} domain={[0, 100]} unit="%" />
            {tooltip()}
            <ChartLegend content={<ChartLegendContent />} />
            <Area isAnimationActive={false} dataKey="memory" type="monotone" stroke="var(--color-memory)" fill="var(--color-memory)" fillOpacity={0.12} strokeWidth={1.5} />
            <Area isAnimationActive={false} dataKey="cpu" type="monotone" stroke="var(--color-cpu)" fill="var(--color-cpu)" fillOpacity={0.2} strokeWidth={1.5} />
          </AreaChart>
        </ChartContainer>
      </Frame>
      {has("netTxBytesPerSecond") || has("netRxBytesPerSecond") ? <Frame title="Сеть" hint="Байты в секунду через физические интерфейсы сервера">
        <ChartContainer config={network} className={FRAME}>
          <AreaChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} />
            {axis}
            <YAxis {...AXIS} width={64} tickFormatter={rate} />
            {tooltip(rate)}
            <ChartLegend content={<ChartLegendContent />} />
            <Area isAnimationActive={false} dataKey="netTxBytesPerSecond" type="monotone" stroke="var(--color-netTxBytesPerSecond)" fill="var(--color-netTxBytesPerSecond)" fillOpacity={0.15} strokeWidth={1.5} />
            <Area isAnimationActive={false} dataKey="netRxBytesPerSecond" type="monotone" stroke="var(--color-netRxBytesPerSecond)" fill="var(--color-netRxBytesPerSecond)" fillOpacity={0.15} strokeWidth={1.5} />
          </AreaChart>
        </ChartContainer>
      </Frame> : null}
      {has("diskWriteBytesPerSecond") || has("diskReadBytesPerSecond") ? <Frame title="Дисковый ввод-вывод" hint="Чтение и запись целых дисков, байты в секунду">
        <ChartContainer config={io} className={FRAME}>
          <AreaChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} />
            {axis}
            <YAxis {...AXIS} width={64} tickFormatter={rate} />
            {tooltip(rate)}
            <ChartLegend content={<ChartLegendContent />} />
            <Area isAnimationActive={false} dataKey="diskWriteBytesPerSecond" type="monotone" stroke="var(--color-diskWriteBytesPerSecond)" fill="var(--color-diskWriteBytesPerSecond)" fillOpacity={0.15} strokeWidth={1.5} />
            <Area isAnimationActive={false} dataKey="diskReadBytesPerSecond" type="monotone" stroke="var(--color-diskReadBytesPerSecond)" fill="var(--color-diskReadBytesPerSecond)" fillOpacity={0.15} strokeWidth={1.5} />
          </AreaChart>
        </ChartContainer>
      </Frame> : null}
    </div>
  );
}

/** Назначение основного сервера во времени: трафик и ответы людям, скорость
 *  страниц, конвейер, сбор. Ресурсы машины — на вкладке «Серверы». */
export function SystemCharts({ points, range }: { points: SystemPoint[]; range: Range }) {
  const data = prepare(points, range);
  const traffic = { requestsPerMinute: { label: "запросов в минуту", color: "var(--chart-2)" } } satisfies ChartConfig;
  const errors = { humanErrors: { label: "ответов 5xx людям", color: "var(--destructive)" } } satisfies ChartConfig;
  const speed = { p95Ms: { label: "p95 ответа страниц, мс", color: "var(--chart-3)" } } satisfies ChartConfig;
  const hits = { hitRatio: { label: "попадания в кэш, %", color: "var(--chart-1)" } } satisfies ChartConfig;
  const pipeline = {
    analysisLagMinutes: { label: "отставание анализа, мин", color: "var(--chart-4)" },
    ingestDelayMinutes: { label: "с последнего пакета, мин", color: "var(--chart-2)" },
  } satisfies ChartConfig;
  const collection = {
    collectedOk: { label: "аккаунтов собрано", color: "var(--chart-1)" },
    collectedFailed: { label: "с ошибкой", color: "var(--destructive)" },
  } satisfies ChartConfig;
  const minGap = range === "week" ? 24 : 32;
  const axis = <XAxis dataKey="label" {...AXIS} minTickGap={minGap} />;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Frame title="Трафик" hint="Все запросы к сайту; ниже — ответы 5xx, полученные людьми">
        <ChartContainer config={traffic} className="aspect-auto h-40 w-full">
          <AreaChart data={data} margin={{ left: 0, right: 8, top: 8 }} syncId="traffic">
            <CartesianGrid vertical={false} />
            <XAxis dataKey="label" hide />
            <YAxis {...AXIS} width={40} />
            {tooltip()}
            <Area isAnimationActive={false} dataKey="requestsPerMinute" type="monotone" stroke="var(--color-requestsPerMinute)" fill="var(--color-requestsPerMinute)" fillOpacity={0.15} strokeWidth={1.5} connectNulls />
          </AreaChart>
        </ChartContainer>
        <ChartContainer config={errors} className="aspect-auto h-16 w-full">
          <BarChart data={data} margin={{ left: 0, right: 8, top: 4 }} syncId="traffic">
            {axis}
            <YAxis {...AXIS} width={40} allowDecimals={false} />
            {tooltip()}
            <Bar isAnimationActive={false} dataKey="humanErrors" fill="var(--color-humanErrors)" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ChartContainer>
      </Frame>
      <Frame title="Скорость страниц" hint="Худшее p95 времени ответа; ниже — доля страниц из кэша nginx">
        <ChartContainer config={speed} className="aspect-auto h-40 w-full">
          <LineChart data={data} margin={{ left: 0, right: 8, top: 8 }} syncId="speed">
            <CartesianGrid vertical={false} />
            <XAxis dataKey="label" hide />
            <YAxis {...AXIS} width={44} />
            {tooltip()}
            <Line isAnimationActive={false} dataKey="p95Ms" type="monotone" stroke="var(--color-p95Ms)" strokeWidth={1.5} dot={false} connectNulls />
          </LineChart>
        </ChartContainer>
        <ChartContainer config={hits} className="aspect-auto h-16 w-full">
          <AreaChart data={data} margin={{ left: 0, right: 8, top: 4 }} syncId="speed">
            {axis}
            <YAxis {...AXIS} width={44} domain={[0, 100]} ticks={[0, 100]} unit="%" />
            {tooltip()}
            <Area isAnimationActive={false} dataKey="hitRatio" type="monotone" stroke="var(--color-hitRatio)" fill="var(--color-hitRatio)" fillOpacity={0.15} strokeWidth={1.5} connectNulls />
          </AreaChart>
        </ChartContainer>
      </Frame>
      <Frame title="Конвейер данных" hint="Отставание очереди анализа и время с последнего пакета Сервера 1">
        <ChartContainer config={pipeline} className={FRAME}>
          <LineChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} />
            {axis}
            <YAxis {...AXIS} width={40} />
            {tooltip()}
            <ChartLegend content={<ChartLegendContent />} />
            <Line isAnimationActive={false} dataKey="analysisLagMinutes" type="monotone" stroke="var(--color-analysisLagMinutes)" strokeWidth={1.5} dot={false} connectNulls />
            <Line isAnimationActive={false} dataKey="ingestDelayMinutes" type="monotone" stroke="var(--color-ingestDelayMinutes)" strokeWidth={1.5} dot={false} connectNulls />
          </LineChart>
        </ChartContainer>
      </Frame>
      <Frame wide title="Сбор по аккаунтам" hint="Завершённые опросы аккаунтов всех площадок: успешные и с ошибкой">
        <ChartContainer config={collection} className={FRAME}>
          <BarChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} />
            {axis}
            <YAxis {...AXIS} width={44} tickFormatter={(value: number) => number.format(value)} />
            {tooltip()}
            <ChartLegend content={<ChartLegendContent />} />
            <Bar isAnimationActive={false} dataKey="collectedOk" stackId="runs" fill="var(--color-collectedOk)" />
            <Bar isAnimationActive={false} dataKey="collectedFailed" stackId="runs" fill="var(--color-collectedFailed)" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ChartContainer>
      </Frame>
    </div>
  );
}
