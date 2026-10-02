"use client";

import { Area, AreaChart, Bar, BarChart, CartesianGrid, ComposedChart, Line, LineChart, XAxis, YAxis } from "recharts";
import {
  ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig,
} from "@/components/ui/chart";
import type { SystemPoint, Visitors } from "@/lib/catalog-api";

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
        <Bar dataKey="views" fill="var(--color-views)" fillOpacity={0.35} radius={[4, 4, 0, 0]} maxBarSize={36} />
        <Line dataKey="visitors" type="monotone" stroke="var(--color-visitors)" strokeWidth={2} dot={{ r: 2.5 }} />
      </ComposedChart>
    </ChartContainer>
  );
}

function prepare(points: SystemPoint[], range: "day" | "week") {
  return points.map((point) => ({
    ...point,
    label: range === "day" ? hourLabel.format(new Date(point.at)) : dayLabel.format(new Date(point.at)),
    stamp: stampLabel.format(new Date(point.at)),
  }));
}

function tooltip() {
  return <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => String(payload?.[0]?.payload?.stamp ?? "")} />} />;
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

/** Графики состояния системы: ресурсы, трафик, конвейер, сбор. */
export function SystemCharts({ points, range }: { points: SystemPoint[]; range: "day" | "week" }) {
  const data = prepare(points, range);
  const resources = {
    cpu: { label: "процессор, %", color: "var(--chart-2)" },
    memory: { label: "память, %", color: "var(--chart-4)" },
  } satisfies ChartConfig;
  const traffic = {
    requestsPerMinute: { label: "запросов в минуту", color: "var(--chart-2)" },
    humanErrors: { label: "ошибки 5xx людям", color: "var(--destructive)" },
  } satisfies ChartConfig;
  const speed = {
    p95Ms: { label: "p95 ответа страниц, мс", color: "var(--chart-3)" },
    hitRatio: { label: "попадания в кэш, %", color: "var(--chart-1)" },
  } satisfies ChartConfig;
  const pipeline = {
    analysisLagMinutes: { label: "отставание анализа, мин", color: "var(--chart-4)" },
    ingestDelayMinutes: { label: "с последнего пакета, мин", color: "var(--chart-2)" },
  } satisfies ChartConfig;
  const collection = {
    collectedOk: { label: "аккаунтов собрано", color: "var(--chart-1)" },
    collectedFailed: { label: "с ошибкой", color: "var(--destructive)" },
  } satisfies ChartConfig;
  const minGap = range === "day" ? 32 : 24;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Frame title="Ресурсы сервера" hint="Средняя загрузка процессора и доля занятой памяти">
        <ChartContainer config={resources} className={FRAME}>
          <AreaChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="label" {...AXIS} minTickGap={minGap} />
            <YAxis {...AXIS} width={36} domain={[0, 100]} unit="%" />
            {tooltip()}
            <ChartLegend content={<ChartLegendContent />} />
            <Area dataKey="memory" type="monotone" stroke="var(--color-memory)" fill="var(--color-memory)" fillOpacity={0.12} strokeWidth={1.5} connectNulls />
            <Area dataKey="cpu" type="monotone" stroke="var(--color-cpu)" fill="var(--color-cpu)" fillOpacity={0.2} strokeWidth={1.5} connectNulls />
          </AreaChart>
        </ChartContainer>
      </Frame>
      <Frame title="Трафик" hint="Все запросы к сайту и ответы 5xx, полученные людьми">
        <ChartContainer config={traffic} className={FRAME}>
          <ComposedChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="label" {...AXIS} minTickGap={minGap} />
            <YAxis yAxisId="rate" {...AXIS} width={40} />
            <YAxis yAxisId="errors" orientation="right" {...AXIS} width={28} allowDecimals={false} />
            {tooltip()}
            <ChartLegend content={<ChartLegendContent />} />
            <Area yAxisId="rate" dataKey="requestsPerMinute" type="monotone" stroke="var(--color-requestsPerMinute)" fill="var(--color-requestsPerMinute)" fillOpacity={0.15} strokeWidth={1.5} connectNulls />
            <Bar yAxisId="errors" dataKey="humanErrors" fill="var(--color-humanErrors)" radius={[2, 2, 0, 0]} />
          </ComposedChart>
        </ChartContainer>
      </Frame>
      <Frame title="Скорость страниц" hint="Худшее p95 времени ответа и доля страниц из кэша nginx">
        <ChartContainer config={speed} className={FRAME}>
          <LineChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="label" {...AXIS} minTickGap={minGap} />
            <YAxis yAxisId="ms" {...AXIS} width={44} />
            <YAxis yAxisId="share" orientation="right" {...AXIS} width={36} domain={[0, 100]} unit="%" />
            {tooltip()}
            <ChartLegend content={<ChartLegendContent />} />
            <Line yAxisId="ms" dataKey="p95Ms" type="monotone" stroke="var(--color-p95Ms)" strokeWidth={1.5} dot={false} connectNulls />
            <Line yAxisId="share" dataKey="hitRatio" type="monotone" stroke="var(--color-hitRatio)" strokeWidth={1.5} dot={false} connectNulls />
          </LineChart>
        </ChartContainer>
      </Frame>
      <Frame title="Конвейер данных" hint="Отставание очереди анализа и время с последнего пакета Сервера 1">
        <ChartContainer config={pipeline} className={FRAME}>
          <LineChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="label" {...AXIS} minTickGap={minGap} />
            <YAxis {...AXIS} width={40} />
            {tooltip()}
            <ChartLegend content={<ChartLegendContent />} />
            <Line dataKey="analysisLagMinutes" type="monotone" stroke="var(--color-analysisLagMinutes)" strokeWidth={1.5} dot={false} connectNulls />
            <Line dataKey="ingestDelayMinutes" type="monotone" stroke="var(--color-ingestDelayMinutes)" strokeWidth={1.5} dot={false} connectNulls />
          </LineChart>
        </ChartContainer>
      </Frame>
      <Frame wide title="Сбор по аккаунтам" hint="Завершённые опросы аккаунтов всех площадок: успешные и с ошибкой">
        <ChartContainer config={collection} className={FRAME}>
          <BarChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="label" {...AXIS} minTickGap={minGap} />
            <YAxis {...AXIS} width={44} tickFormatter={(value: number) => number.format(value)} />
            {tooltip()}
            <ChartLegend content={<ChartLegendContent />} />
            <Bar dataKey="collectedOk" stackId="runs" fill="var(--color-collectedOk)" />
            <Bar dataKey="collectedFailed" stackId="runs" fill="var(--color-collectedFailed)" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ChartContainer>
      </Frame>
    </div>
  );
}
