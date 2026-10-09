"use client";

import type * as React from "react";
import { Area, AreaChart, Bar, BarChart, Cell, Pie, PieChart, PolarAngleAxis, RadialBar, RadialBarChart, XAxis, YAxis } from "recharts";
import { Card } from "@/components/ui/card";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import type { CatalogStatus, SystemLivePoint, SystemOverview, SystemPoint } from "@/lib/catalog-api";
import { PLATFORM_LONG_LABELS } from "@/lib/format";
import { LiveNumber } from "./live-number";
import { useLiveHost } from "./live-host";
import { bytes, percent, rate } from "./units";

const MOSCOW = "Europe/Moscow";
const clock = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: MOSCOW });
const number = new Intl.NumberFormat("ru-RU");
/** Спарклайн карточки — последние пять минут живого буфера. */
const SPARK_MS = 5 * 60_000;

type Host = NonNullable<SystemOverview["host"]>;
type Spark = { at: string; stamp: string } & Record<string, number | string | null>;

/** Кольцо доли: трек — muted, дуга — цвет ряда; число в центре — текстом, не цветом. */
function Ring({ value, color, label, children }: { value: number | null; color: string; label: string; children: React.ReactNode }) {
  const config = { value: { label, color } } satisfies ChartConfig;
  return (
    <div className="relative size-[92px] shrink-0">
      <ChartContainer config={config} className="aspect-square size-full" initialDimension={{ width: 92, height: 92 }}>
        <RadialBarChart data={[{ value: value ?? 0, fill: "var(--color-value)" }]} startAngle={90} endAngle={-270}
          innerRadius="80%" outerRadius="100%" barSize={8}>
          <PolarAngleAxis type="number" domain={[0, 100]} tick={false} axisLine={false} />
          <RadialBar dataKey="value" background={{ fill: "var(--muted)" }} cornerRadius={6} animationDuration={700} />
        </RadialBarChart>
      </ChartContainer>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center leading-tight">{children}</div>
    </div>
  );
}

/** Доли рисуются по своему размаху (видно движение), скорости — от нуля. */
function Sparkline({ data, series, unit, fromZero = false }: {
  data: Spark[]; series: { key: string; label: string; color: string }[]; unit: (value: number) => string; fromZero?: boolean;
}) {
  const config = Object.fromEntries(series.map((item) => [item.key, { label: item.label, color: item.color }])) satisfies ChartConfig;
  if (data.length < 2) return <div className="bg-muted/50 h-12 rounded-md" aria-hidden="true" />;
  return (
    <ChartContainer config={config} className="aspect-auto h-12 w-full" initialDimension={{ width: 240, height: 48 }}>
      <AreaChart data={data} margin={{ top: 4, bottom: 0, left: 0, right: 0 }}>
        <XAxis dataKey="stamp" hide />
        <YAxis hide domain={fromZero ? [0, "auto"] : ["dataMin - 2", "dataMax + 2"]} />
        <ChartTooltip cursor={{ stroke: "var(--border)" }} content={<ChartTooltipContent indicator="line"
          labelFormatter={(_, payload) => String(payload?.[0]?.payload?.stamp ?? "")}
          valueFormatter={(value) => unit(Number(value))} />} />
        {series.map((item) => (
          <Area key={item.key} dataKey={item.key} type="monotone" stroke={`var(--color-${item.key})`} fill={`var(--color-${item.key})`}
            fillOpacity={0.15} strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />
        ))}
      </AreaChart>
    </ChartContainer>
  );
}

function Metric({ label, live, ring, children, spark, footer }: {
  label: string; live: boolean; ring?: React.ReactNode; children: React.ReactNode; spark?: React.ReactNode; footer?: React.ReactNode;
}) {
  return (
    <Card className="min-w-0 gap-3 p-4" data-metric={label}>
      <div className="flex items-center justify-between gap-2">
        <p className="font-heading text-sm font-semibold tracking-tight">{label}</p>
        {live ? <span className="text-muted-foreground inline-flex items-center gap-1.5 text-[11px]" title="Обновляется каждые несколько секунд">
          <span className="relative flex size-1.5" aria-hidden="true">
            <span className="bg-success absolute inline-flex size-full animate-ping rounded-full opacity-60 motion-reduce:hidden" />
            <span className="bg-success relative inline-flex size-1.5 rounded-full" />
          </span>live</span> : null}
      </div>
      <div className="flex items-center gap-4">
        {ring}
        <div className="text-muted-foreground min-w-0 space-y-1 text-xs">{children}</div>
      </div>
      {spark}
      {footer ? <p className="text-muted-foreground text-xs">{footer}</p> : null}
    </Card>
  );
}

function Center({ value, suffix = "%", caption }: { value: number | null; suffix?: string; caption?: string }) {
  return <>
    {value == null ? <span className="font-heading text-lg font-semibold">—</span>
      : <LiveNumber value={value} decimals={value < 100 && !Number.isInteger(value) ? 1 : 0} suffix={suffix} className="font-heading text-lg font-semibold" />}
    {caption ? <span className="text-muted-foreground text-[10px]">{caption}</span> : null}
  </>;
}

function stamp(at: string) {
  return clock.format(new Date(at));
}

/** Пять карточек ресурсов: CPU, RAM, диск, сеть и службы. Кольца и
 *  спарклайны идут от живого буфера API; пока его нет (первый запрос,
 *  перезапуск API) — от последнего минутного снимка. */
export function HostCards({ host, fallback }: { host: Host; fallback: SystemPoint[] }) {
  const live = useLiveHost();
  const latest: SystemLivePoint | undefined = live.points[live.points.length - 1];
  const isLive = live.state === "live" && !!latest;
  const edge = latest ? Date.parse(latest.at) - SPARK_MS : 0;
  const recent: Spark[] = isLive
    ? live.points.filter((point) => Date.parse(point.at) >= edge).map((point) => ({ ...point, stamp: stamp(point.at) }))
    : fallback.slice(-24).map((point) => ({ ...point, stamp: stamp(point.at) }));
  const cores = live.meta?.cores ?? host.cores ?? 1;
  const cpu = isLive ? latest.cpu : host.cpuPercent;
  const memoryTotal = live.meta?.memoryTotalBytes ?? host.memoryTotalBytes;
  const memoryUsed = isLive ? latest.memoryUsedBytes : host.memoryUsedBytes;
  const memory = isLive ? latest.memory : percent(host.memoryUsedBytes, host.memoryTotalBytes, 1);
  const swap = isLive ? latest.swapUsedBytes : host.swapUsedBytes;
  const diskTotal = live.meta?.diskTotalBytes ?? host.diskTotalBytes;
  const diskFree = live.meta?.diskFreeBytes ?? host.diskFreeBytes;
  const diskUsed = diskTotal != null && diskFree != null ? diskTotal - diskFree : null;
  const disk = percent(diskUsed, diskTotal, 1);
  const units = percent(host.unitsActive, host.unitsTotal, 0);
  const load = host.load.length ? host.load : latest?.load != null ? [latest.load] : [];
  const pct = (value: number) => `${value.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
  return (
    <div data-testid="host-cards" className="mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      <Metric label="CPU" live={isLive}
        ring={<Ring value={cpu} color="var(--chart-2)" label="CPU"><Center value={cpu} caption={`${cores} ${cores === 1 ? "ядро" : cores < 5 ? "ядра" : "ядер"}`} /></Ring>}
        spark={<Sparkline data={recent} unit={pct} series={[{ key: "cpu", label: "CPU", color: "var(--chart-2)" }]} />}>
        <p>load average</p>
        <p className="text-foreground font-medium tabular-nums">{load.map((value) => value.toFixed(2)).join(" · ") || "—"}</p>
        <p>{load[0] != null && load[0] > cores * 2 ? "выше двух на ядро" : "в пределах ядер"}</p>
      </Metric>
      <Metric label="RAM" live={isLive}
        ring={<Ring value={memory} color="var(--chart-4)" label="RAM"><Center value={memory} caption="занято" /></Ring>}
        spark={<Sparkline data={recent} unit={pct} series={[{ key: "memory", label: "RAM", color: "var(--chart-4)" }]} />}>
        <p className="text-foreground font-medium tabular-nums">{bytes(memoryUsed)}</p>
        <p>из {bytes(memoryTotal)}</p>
        <p>swap {bytes(swap)}</p>
      </Metric>
      <Metric label="Disk" live={isLive}
        ring={<Ring value={disk} color="var(--chart-3)" label="Disk"><Center value={disk} caption="занято" /></Ring>}
        spark={isLive ? <Sparkline data={recent} unit={rate} fromZero series={[
          { key: "diskWriteBytesPerSecond", label: "запись", color: "var(--chart-3)" },
          { key: "diskReadBytesPerSecond", label: "чтение", color: "var(--chart-5)" },
        ]} /> : undefined}>
        <p className="text-foreground font-medium tabular-nums">{bytes(diskFree)}</p>
        <p>свободно из {bytes(diskTotal)}</p>
        {isLive ? <p className="tabular-nums">запись {rate(latest.diskWriteBytesPerSecond)}</p> : null}
      </Metric>
      <Metric label="Network" live={isLive}
        spark={isLive ? <Sparkline data={recent} unit={rate} fromZero series={[
          { key: "netTxBytesPerSecond", label: "отдано", color: "var(--chart-1)" },
          { key: "netRxBytesPerSecond", label: "получено", color: "var(--chart-9)" },
        ]} /> : undefined}
        footer={isLive ? undefined : "Скорости сети появятся с живым буфером API."}>
        <p className="flex items-baseline gap-2"><span className="bg-chart-1 inline-block size-2 rounded-full" aria-hidden="true" />отдано
          <b className="text-foreground font-heading text-base tabular-nums">{isLive ? rate(latest.netTxBytesPerSecond) : "—"}</b></p>
        <p className="flex items-baseline gap-2"><span className="bg-chart-9 inline-block size-2 rounded-full" aria-hidden="true" />получено
          <b className="text-foreground font-heading text-base tabular-nums">{isLive ? rate(latest.netRxBytesPerSecond) : "—"}</b></p>
      </Metric>
      <Metric label="Services" live={false}
        ring={<Ring value={units} color={host.failedUnits.length ? "var(--destructive)" : "var(--chart-1)"} label="Services">
          <Center value={host.unitsActive ?? null} suffix="" caption={`из ${host.unitsTotal ?? "—"}`} />
        </Ring>}
        footer="Остальные службы проекта — таймеры: они запускаются по расписанию.">
        <p className="text-foreground font-medium">{host.failedUnits.length ? "упали:" : "упавших нет"}</p>
        {host.failedUnits.map((unit) => <p key={unit} className="text-destructive truncate" title={unit}>{unit.replace(/^m-ranked-target-|\.service$/g, "")}</p>)}
      </Metric>
    </div>
  );
}

const PARTS = [
  { key: "database", label: "база", color: "var(--chart-2)" },
  { key: "state", label: "данные служб", color: "var(--chart-4)" },
  { key: "releases", label: "релизы", color: "var(--chart-3)" },
  { key: "pageCache", label: "кэш страниц", color: "var(--chart-1)" },
] as const;

/** Хранилище сразу под ресурсами: диск, весь проект по частям, база. */
export function StorageCards({ storage }: { storage: CatalogStatus["storage"] | null }) {
  const total = storage?.diskTotalBytes ?? null, free = storage?.diskFreeBytes ?? null;
  const used = total !== null && free !== null ? Math.max(0, total - free) : null;
  const parts = storage?.projectParts;
  const values: Record<(typeof PARTS)[number]["key"], number | null> = {
    database: storage?.databaseBytes ?? null, state: parts?.stateBytes ?? null,
    releases: parts?.releasesBytes ?? null, pageCache: parts?.pageCacheBytes ?? null,
  };
  const slices = PARTS.map((part) => ({ ...part, value: values[part.key] ?? 0 })).filter((part) => part.value > 0);
  const config = Object.fromEntries(PARTS.map((part) => [part.key, { label: part.label, color: part.color }])) satisfies ChartConfig;
  const diskShare = percent(used, total);
  const projectShare = percent(storage?.projectBytes, used);
  const databaseShare = percent(storage?.databaseBytes ?? null, used);
  return (
    <div data-testid="storage-cards" className="mb-5 grid gap-4 md:grid-cols-3">
      <Metric label="Диск сервера" live={false}
        ring={<Ring value={diskShare} color="var(--chart-3)" label="Диск сервера"><Center value={diskShare} caption="занято" /></Ring>}
        footer="Свободное место — по df раздела с базой.">
        <p className="text-foreground font-heading text-base font-semibold tabular-nums">{bytes(used)}</p>
        <p>из {bytes(total)}</p>
        <p>свободно <b className="text-foreground">{bytes(free)}</b></p>
      </Metric>
      <Metric label="Весь проект m-ranked" live={false}
        ring={<div className="relative size-[92px] shrink-0">
          {slices.length ? <ChartContainer config={config} className="aspect-square size-full" initialDimension={{ width: 92, height: 92 }}>
            <PieChart>
              <ChartTooltip content={<ChartTooltipContent hideLabel nameKey="key" valueFormatter={(value) => bytes(Number(value))} />} />
              <Pie data={slices} dataKey="value" nameKey="key" innerRadius="66%" outerRadius="100%" paddingAngle={2} stroke="var(--card)" strokeWidth={2}>
                {slices.map((slice) => <Cell key={slice.key} fill={`var(--color-${slice.key})`} />)}
              </Pie>
            </PieChart>
          </ChartContainer> : <div className="border-muted size-full rounded-full border-8" />}
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center leading-tight">
            <span className="font-heading text-sm font-semibold">{bytes(storage?.projectBytes)}</span>
          </div>
        </div>}
        footer={projectShare === null ? "Первый замер каталогов — с первым снимком сервера." : `${projectShare}% от занятого места; каталоги меряются раз в 6 часов.`}>
        <ul className="space-y-0.5">
          {PARTS.map((part) => (
            <li key={part.key} className="flex items-center gap-1.5">
              <span className="inline-block size-2 shrink-0 rounded-[2px]" style={{ background: part.color }} aria-hidden="true" />
              <span>{part.label}</span><b className="text-foreground ml-auto pl-2 font-medium tabular-nums">{bytes(values[part.key])}</b>
            </li>
          ))}
        </ul>
      </Metric>
      <Metric label="База результатов парсинга" live={false}
        ring={<Ring value={databaseShare} color="var(--chart-2)" label="База"><Center value={databaseShare} caption="от занятого" /></Ring>}
        footer="PostgreSQL целиком: история замеров, анализ, каталог.">
        <p className="text-foreground font-heading text-base font-semibold tabular-nums">{bytes(storage?.databaseBytes)}</p>
        <p>{databaseShare === null ? "размер не предоставлен сервером" : `${databaseShare}% занятого места на диске`}</p>
      </Metric>
    </div>
  );
}

const PLATFORM_COLORS: Record<string, string> = {
  telegram: "var(--chart-2)", vk: "var(--chart-9)", max: "var(--chart-4)", rutube: "var(--chart-8)",
};

/** Сбор за период: успешные и неудачные опросы по площадкам — горизонтальные
 *  столбцы с общей шкалой; ошибки отдельным сегментом цвета ошибки. */
export function CollectionChart({ rows }: { rows: SystemOverview["collection"] }) {
  const data = rows.map((row) => ({ ...row, name: PLATFORM_LONG_LABELS[row.platform], color: PLATFORM_COLORS[row.platform] }));
  const config = {
    ok: { label: "успешно", color: "var(--chart-2)" },
    failed: { label: "с ошибкой", color: "var(--destructive)" },
  } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className="aspect-auto h-44 w-full" initialDimension={{ width: 480, height: 176 }}>
      <BarChart data={data} layout="vertical" margin={{ left: 0, right: 12, top: 4, bottom: 0 }} barCategoryGap={8}>
        <XAxis type="number" hide />
        <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} width={84} fontSize={11} />
        <ChartTooltip cursor={{ fill: "var(--muted)", opacity: 0.5 }} content={<ChartTooltipContent valueFormatter={(value) => number.format(Number(value))} />} />
        <Bar dataKey="ok" stackId="runs" radius={[4, 0, 0, 4]} animationDuration={600}>
          {data.map((row) => <Cell key={row.platform} fill={row.color} />)}
        </Bar>
        <Bar dataKey="failed" stackId="runs" fill="var(--color-failed)" radius={[0, 4, 4, 0]} minPointSize={(value) => (Number(value) > 0 ? 3 : 0)} />
      </BarChart>
    </ChartContainer>
  );
}

