"use client";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ReferenceArea, ReferenceLine, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";
import { duration, legacyDate } from "@/lib/format";
import { observationGaps } from "@/lib/observation-gaps";
import { historyMetricValue, historyMetricTooltip, historyRatioTooltip, metricLabel, metricNoun as noun, type HistoryMetric as Metric } from "@/lib/history-metrics";
import { cn } from "@/lib/utils";
import type { HistorySnapshot } from "@/lib/types";
function shortDate(value:string) {return legacyDate(value).replace(/\.\d{4},/, ",");}

/** Evidence samples are drawn as a larger diamond, so a published signal
 *  boundary is distinguishable from an ordinary observation without colour. */
function SampleDot(props: { cx?: number; cy?: number; fill?: string; evidence?: boolean }) {
  const { cx, cy, fill, evidence } = props;
  if (cx === undefined || cy === undefined || !Number.isFinite(cx) || !Number.isFinite(cy)) return null;
  if (evidence) {
    return <rect x={cx - 5} y={cy - 5} width={10} height={10} transform={`rotate(45 ${cx} ${cy})`} fill={fill} stroke="var(--background)" strokeWidth={3} />;
  }
  return <circle cx={cx} cy={cy} r={3} fill={fill} stroke="var(--background)" strokeWidth={1} />;
}

/** Two lines per tick: the wall clock of the sample and the age of the
 *  publication at that moment, exactly as the inherited axis read. */
function TimeTick({ x, y, payload, rows }: {
  x?: number | string; y?: number | string; payload?: { value?: number }; rows: HistorySnapshot[];
}) {
  const value = payload?.value;
  if (x === undefined || y === undefined || typeof value !== "number" || !rows.length) return null;
  const nearest = rows.reduce((best, row) =>
    Math.abs(Date.parse(row.observedAt) - value) < Math.abs(Date.parse(best.observedAt) - value) ? row : best, rows[0]!);
  return (
    <text x={x} y={y} textAnchor="middle" fill="var(--muted-foreground)" fontSize={11}>
      <tspan x={x} dy="0.8em">{shortDate(new Date(value).toISOString())}</tspan>
      <tspan x={x} dy="1.1em">{nearest.synthetic ? "момент публикации" : `через ${duration(nearest.ageHours * 3600)}`}</tspan>
    </text>
  );
}

export default function PublicationPlot({ rows, metrics, delta, selectedId, onSelect, onActivate, platform, evidenceIds, hidden, scale }: {
  rows: HistorySnapshot[]; metrics: Metric[]; delta: boolean; selectedId?: string;
  onSelect: (id: string) => void; onActivate: (id: string) => void; platform:string;evidenceIds:ReadonlySet<string>; hidden: ReadonlySet<string>; scale: "shared" | "auto";
}) {
  const [tooltip, setTooltip] = useState<string | null>(null);
  const active = useRef(0);
  const chartId = useId();

  const at = useCallback((row: HistorySnapshot) => Date.parse(row.observedAt), []);
  const data = useMemo(() => rows.map((row) => {
    const point: Record<string, number | null | string | boolean> = {
      t: at(row), snapshotId: row.snapshotId, evidence: evidenceIds.has(row.snapshotId),
    };
    for (const metric of metrics) point[metric.key] = historyMetricValue(row, metric, delta);
    return point;
  }), [rows, metrics, delta, evidenceIds, at]);

  const gaps = useMemo(() => observationGaps(rows), [rows]);
  const firstAt = rows.length ? at(rows[0]!) : 0;
  const lastAt = rows.length ? at(rows[rows.length - 1]!) : 1;

  const config = useMemo(() => {
    const value: ChartConfig = {};
    for (const metric of metrics) {
      value[metric.key] = { label: `${delta ? "Прирост" : "Всего"} ${noun(metric, platform)}`, color: metric.color };
    }
    return value;
  }, [metrics, delta, platform]);

  const commonTitle = metrics.map((metric) => metricLabel(metric, platform)).join(" и ");
  const axisTitle = metrics.length > 2
    ? delta ? "Прирост метрик" : "Метрики"
    : delta ? `Прирост: ${commonTitle.toLowerCase()}` : commonTitle;

  const reading = useCallback((row: HistorySnapshot) => [
    legacyDate(row.observedAt),
    ...metrics.filter((metric) => !hidden.has(metric.key)).map((metric) => historyMetricTooltip(row, metric, platform, delta)),
    !delta ? historyRatioTooltip(row, platform) : "",
  ].filter(Boolean).join(" · "), [metrics, hidden, platform, delta]);

  // Selecting a row elsewhere moves the chart's own cursor to that sample.
  useEffect(() => {
    if (!selectedId) return;
    const index = rows.findIndex((row) => row.snapshotId === selectedId);
    if (index >= 0) active.current = index;
  }, [selectedId, rows]);

  function keyboard(key?: string) {
    if (!rows.length) return;
    if (key === "ArrowRight") active.current = Math.min(rows.length-1,active.current+1);
    if (key === "ArrowLeft") active.current = Math.max(0,active.current-1);
    if (key === "Home") active.current = 0;
    if (key === "End") active.current = rows.length-1;
    active.current = Math.max(0,Math.min(rows.length-1,active.current));
    const row = rows[active.current]!;
    onSelect(row.snapshotId);
    setTooltip(reading(row));
  }
  function closeTooltip() { setTooltip(null); }

  const selectedAt = selectedId
    ? rows.find((row) => row.snapshotId === selectedId)?.observedAt
    : undefined;

  /** Resolves a pointer position on the plot to the sample nearest that instant. */
  const nearestRow = useCallback((instant: unknown) => {
    if (typeof instant !== "number" || !rows.length) return null;
    return rows.reduce((best, row) =>
      Math.abs(at(row) - instant) < Math.abs(at(best) - instant) ? row : best, rows[0]!);
  }, [rows, at]);

  const axes = scale === "shared"
    ? [<YAxis key="y" yAxisId="y" tickLine={false} axisLine={false} width={64} allowDecimals={false}
        label={{ value: axisTitle, angle: -90, position: "insideLeft", style: { textAnchor: "middle" }, fill: "var(--muted-foreground)" }} />]
    : metrics.map((metric, index) => (
        <YAxis key={metric.key} yAxisId={metric.key} orientation={index % 2 ? "right" : "left"}
          hide={hidden.has(metric.key)} tickLine={false} axisLine={false} width={64} allowDecimals={false}
          label={{ value: metricLabel(metric, platform), angle: -90, position: index % 2 ? "insideRight" : "insideLeft", style: { textAnchor: "middle" }, fill: "var(--muted-foreground)" }} />
      ));
  const axisFor = (metric: Metric) => (scale === "shared" ? "y" : metric.key);

  const shared = {
    data,
    margin: { left: 12, right: 12, top: 8, bottom: 28 },
    onClick: (state: { activeLabel?: unknown }) => {
      const row = nearestRow(state?.activeLabel);
      if (row) onActivate(row.snapshotId);
    },
  };

  const children = (
    <>
      <CartesianGrid vertical={false} />
      {/* The renderer shades the stretches where no observation exists. */}
      {gaps.map((gap) => (
        <ReferenceArea key={`${gap.from}-${gap.to}`} x1={gap.from} x2={gap.to} yAxisId={axisFor(metrics[0]!)}
          fill="var(--muted-foreground)" fillOpacity={0.12} ifOverflow="hidden" />
      ))}
      <XAxis dataKey="t" type="number" domain={[firstAt, lastAt === firstAt ? firstAt + 1 : lastAt]}
        scale="time" tickLine={false} axisLine={false} height={44} interval="preserveStartEnd"
        tick={(props) => <TimeTick {...props} rows={rows} />}
        label={{ value: "Время замера и возраст публикации", position: "insideBottom", offset: -6, fill: "var(--muted-foreground)" }} />
      {axes}
      <ChartTooltip
        cursor={{ strokeDasharray: "4 4" }}
        content={(props) => (
          <SnapshotTooltip {...props} metrics={metrics} hidden={hidden} platform={platform} delta={delta} nearestRow={nearestRow} />
        )}
      />
      {selectedAt ? (
        <ReferenceLine x={Date.parse(selectedAt)} yAxisId={axisFor(metrics[0]!)} stroke="var(--foreground)" strokeOpacity={0.45} strokeDasharray="3 3" />
      ) : null}
    </>
  );

  return <>

    <div
      role="img"
      tabIndex={0}
      data-chart-ready={rows.length > 0}
      aria-label={delta ? "Прирост между замерами" : "Накопление показателей"}
      aria-describedby={`${chartId}-instructions ${chartId}-tooltip`}
      className="focus-visible:ring-ring/50 h-[360px] w-full rounded-md outline-none focus-visible:ring-[3px]"
      onFocus={() => keyboard()}
      onBlur={closeTooltip}
      onKeyDown={(event) => {
        if(event.key === "Escape") { closeTooltip(); }
        else if(event.key === "Enter" || event.key === " ") { event.preventDefault();const row=rows[active.current];if(row) onActivate(row.snapshotId); }
        else if(["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) { event.preventDefault();keyboard(event.key); }
      }}
    >
      <ChartContainer config={config} className="h-full w-full">
        {delta ? (
          <BarChart {...shared}>
            {children}
            {metrics.map((metric) => (
              <Bar key={metric.key} dataKey={metric.key} yAxisId={axisFor(metric)} hide={hidden.has(metric.key)}
                isAnimationActive animationDuration={420} maxBarSize={18}>
                {data.map((point) => (
                  <Cell
                    key={String(point.snapshotId)}
                    // A negative correction reads as a correction, not as growth.
                    fill={(point[metric.key] as number ?? 0) < 0 ? "var(--destructive)" : metric.color}
                    stroke={point.evidence ? "var(--foreground)" : undefined}
                    strokeWidth={point.evidence ? 2 : 0}
                  />
                ))}
              </Bar>
            ))}
          </BarChart>
        ) : (
          <AreaChart {...shared}>
            <defs>
              {metrics.map((metric) => (
                <linearGradient key={metric.key} id={`${chartId}-${metric.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={metric.color} stopOpacity={0.22} />
                  <stop offset="95%" stopColor={metric.color} stopOpacity={0.02} />
                </linearGradient>
              ))}
            </defs>
            {children}
            {metrics.map((metric) => (
              <Area key={metric.key} dataKey={metric.key} yAxisId={axisFor(metric)} hide={hidden.has(metric.key)}
                type="monotone" stroke={metric.color} strokeWidth={3} fill={`url(#${chartId}-${metric.key})`}
                connectNulls={false} isAnimationActive animationDuration={420}
                activeDot={{ r: 6 }}
                dot={(props) => {
                  // Recharts types the per-point dot props loosely; the shape
                  // this chart supplies is narrowed at the boundary.
                  const dot = props as unknown as { cx?: number; cy?: number; payload?: { evidence?: boolean }; key?: string };
                  return <SampleDot key={dot.key} cx={dot.cx} cy={dot.cy} fill={metric.color} evidence={dot.payload?.evidence} />;
                }}
              />
            ))}
          </AreaChart>
        )}
      </ChartContainer>
    </div>
    <p id={`${chartId}-instructions`} className="sr-only">Стрелки влево и вправо выбирают замер; Home и End — первый и последний. Enter или пробел открывает соответствующую строку таблицы. Escape закрывает подсказку.</p>
    <div id={`${chartId}-tooltip`} role="tooltip" aria-hidden={!tooltip} className={cn("text-muted-foreground text-sm", tooltip ? "py-2" : "sr-only")}>{tooltip}</div>
  </>;
}

/** Reads exactly what the inherited tooltip read: the sample's wall clock, each
 *  visible metric, the reaction-to-view share and whether the point is the
 *  synthetic moment of publication. */
function SnapshotTooltip({ active, label, metrics, hidden, platform, delta, nearestRow }: {
  active?: boolean;
  label?: unknown;
  metrics: Metric[];
  hidden: ReadonlySet<string>;
  platform: string;
  delta: boolean;
  nearestRow: (instant: unknown) => HistorySnapshot | null;
}) {
  if (!active) return null;
  const row = nearestRow(label);
  if (!row) return null;
  const ratio = !delta ? historyRatioTooltip(row, platform) : "";
  return (
    <div className="border-border/50 bg-background grid min-w-[12rem] gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl">
      <div className="font-medium">{shortDate(row.observedAt)}</div>
      {row.synthetic ? <div className="text-muted-foreground">Момент публикации · синтетическая точка</div> : null}
      {metrics.filter((metric) => !hidden.has(metric.key)).map((metric) => (
        <div key={metric.key} className="flex items-center gap-2">
          <span aria-hidden="true" className="size-2.5 shrink-0 rounded-[2px]" style={{ background: metric.color }} />
          <span className="text-foreground tabular">{historyMetricTooltip(row, metric, platform, delta)}</span>
        </div>
      ))}
      {ratio ? <div className="text-muted-foreground tabular">{ratio}</div> : null}
    </div>
  );
}

