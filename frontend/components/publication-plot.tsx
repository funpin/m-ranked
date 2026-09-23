"use client";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, XAxis, YAxis, usePlotArea, useXAxisScale } from "recharts";
import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";
import { axisNumber, duration, legacyDate } from "@/lib/format";
import { elapsedSincePublication } from "@/lib/history-data";
import { historyMetricValue, historyMetricTooltip, historyRatioTooltip, metricLabel, metricNoun as noun, type HistoryMetric as Metric } from "@/lib/history-metrics";
import { cn } from "@/lib/utils";
import type { CollectorGap, HistorySnapshot } from "@/lib/types";
import type { SignalMarker } from "@/lib/anomaly";
function shortDate(value:string) {return legacyDate(value).replace(/\.\d{4},/, ",");}

/** Больше этого числа столбцов прироста на экране уже не различить: при
 *  ширине графика около девятисот точек каждый столбец становится тоньше
 *  волоса, и картинка перестаёт читаться. */
const MAX_BARS = 56;
const GAP_MERGE_DISTANCE_PX = 2;

/** Draw confirmed collector gaps as subpaths of one SVG element.
 *
 * A noisy account can have hundreds of short gaps. Rendering each one as a
 * Recharts ReferenceArea created thousands of React/SVG nodes across the two
 * plots and made the whole page expensive to paint while scrolling. Gaps whose
 * visible separation is two pixels or less are merged at the current scale:
 * zooming in separates them again. The textual count and duration remain exact.
 * One path keeps the overlay at one DOM node per chart. */
function CollectorGapOverlay({ gaps }: { gaps: readonly CollectorGap[] }) {
  const scale = useXAxisScale();
  const plot = usePlotArea();
  const overlay = useMemo(() => {
    if (!scale || !plot || !gaps.length) return { path: "", blocks: 0 };
    const minX = plot.x;
    const maxX = plot.x + plot.width;
    const minY = plot.y;
    const maxY = plot.y + plot.height;
    const projected = gaps.flatMap((gap) => {
      const from = scale(Date.parse(gap.from));
      const to = scale(Date.parse(gap.to));
      if (from === undefined || to === undefined) return [];
      const left = Math.max(minX, Math.min(from, to));
      const right = Math.min(maxX, Math.max(from, to));
      if (!Number.isFinite(left) || !Number.isFinite(right) || right <= left) return [];
      return [{ left, right }];
    }).sort((a,b) => a.left-b.left || a.right-b.right);
    const blocks: {left:number;right:number}[] = [];
    for (const range of projected) {
      const previous = blocks.at(-1);
      if (previous && range.left <= previous.right + GAP_MERGE_DISTANCE_PX) {
        previous.right = Math.max(previous.right, range.right);
      } else {
        blocks.push({...range});
      }
    }
    const path = blocks.map(({left,right}) =>
      `M${left.toFixed(2)},${minY.toFixed(2)}H${right.toFixed(2)}V${maxY.toFixed(2)}H${left.toFixed(2)}Z`,
    ).join("");
    return {path,blocks:blocks.length};
  }, [gaps, plot, scale]);
  return overlay.path ? <path className="collector-gap" data-gap-blocks={overlay.blocks} data-gap-count={gaps.length}
    d={overlay.path} fill="var(--destructive)" fillOpacity={0.13}
    stroke="var(--destructive)" strokeOpacity={0.45} strokeWidth={1} pointerEvents="none" /> : null;
}

/** Интервалы признаков: полупрозрачная полоса под линиями и символ признака
 *  над ней. Полоса бледнее ромбов границ и под ними, поэтому ромб остаётся
 *  читаемой отметкой точки, а полоса — отметкой промежутка. Выбранный в
 *  карточке признак подсвечивается ярче и обводится пунктиром. */
function SignalOverlay({ markers, highlight }: { markers: readonly SignalMarker[]; highlight?: string }) {
  const scale = useXAxisScale();
  const plot = usePlotArea();
  if (!scale || !plot || !markers.length) return null;
  return <g className="signal-markers" pointerEvents="none">
    {markers.map((marker) => {
      const from = scale(marker.from), to = scale(marker.to);
      if (from === undefined || to === undefined) return null;
      const left = Math.max(plot.x, Math.min(from, to));
      const right = Math.min(plot.x + plot.width, Math.max(from, to, Math.min(from, to) + 2));
      if (!Number.isFinite(left) || !Number.isFinite(right) || right <= left) return null;
      const active = marker.id === highlight;
      return <g key={marker.id} data-signal-marker={marker.pattern} data-highlighted={active || undefined}>
        <rect x={left} y={plot.y} width={right - left} height={plot.height} fill="var(--chart-3)"
          fillOpacity={active ? 0.2 : 0.08} stroke={active ? "var(--chart-3)" : "none"} strokeDasharray="4 3" strokeWidth={1.5} />
        <text x={left + 3} y={plot.y + 14} fontSize={13} fill="var(--foreground)" fillOpacity={0.85}>
          {marker.symbol}<title>{marker.title}</title>
        </text>
      </g>;
    })}
  </g>;
}

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
function TimeTick({ x, y, payload, rows, index, visibleTicksCount }: {
  x?: number | string; y?: number | string; payload?: { value?: number }; rows: HistorySnapshot[];
  index?: number; visibleTicksCount?: number;
}) {
  const value = payload?.value;
  if (x === undefined || y === undefined || typeof value !== "number" || !rows.length) return null;
  const nearest = rows.reduce((best, row) =>
    Math.abs(Date.parse(row.observedAt) - value) < Math.abs(Date.parse(best.observedAt) - value) ? row : best, rows[0]!);
  const anchor: "start" | "middle" | "end" = index === 0 ? "start" : index === (visibleTicksCount ?? 0) - 1 ? "end" : "middle";
  return (
    <text x={x} y={y} textAnchor={anchor} fill="var(--muted-foreground)" fontSize={11}>
      <tspan x={x} dy="0.8em">{shortDate(new Date(value).toISOString())}</tspan>
      <tspan x={x} dy="1.1em">{nearest.synthetic ? "момент публикации" : `через ${duration(nearest.ageHours * 3600)}`}</tspan>
    </text>
  );
}

export default function PublicationPlot({ rows, metrics, delta, selectedId, onSelect, onActivate, platform, publishedAt, evidenceIds, hidden, scale, gaps, markers = [], highlight }: {
  rows: HistorySnapshot[]; metrics: Metric[]; delta: boolean; selectedId?: string;
  onSelect: (id: string) => void; onActivate: (id: string) => void; platform:string;publishedAt:string;evidenceIds:ReadonlySet<string>; hidden: ReadonlySet<string>; scale: "shared" | "auto"; gaps: readonly CollectorGap[];
  markers?: readonly SignalMarker[]; highlight?: string;
}) {
  const [tooltip, setTooltip] = useState<string | null>(null);
  const active = useRef(0);
  const chartId = useId();

  const at = useCallback((row: HistorySnapshot) => Date.parse(row.observedAt), []);
  const data = useMemo(() => {
    const points = rows.map((row) => {
      const point: Record<string, number | null | string | boolean> = {
        t: at(row), snapshotId: row.snapshotId, evidence: evidenceIds.has(row.snapshotId),
      };
      for (const metric of metrics) point[metric.key] = historyMetricValue(row, metric, delta);
      return point;
    });
    // Столбцы прироста при сотне замеров вырождаются в частокол шириной в
    // пиксель. Соседние замеры складываются в равные группы: прирост —
    // величина складываемая, поэтому сумма по группе остаётся тем же
    // приростом, только за более длинный промежуток. Накопление так сворачивать
    // нельзя — там значения не складываются, — и линия его не требует.
    if (!delta || points.length <= MAX_BARS) return points;
    const size = Math.ceil(points.length / MAX_BARS);
    const grouped: typeof points = [];
    for (let start = 0; start < points.length; start += size) {
      const chunk = points.slice(start, start + size);
      const last = chunk[chunk.length - 1]!;
      const merged: Record<string, number | null | string | boolean> = {
        t: last.t, snapshotId: last.snapshotId,
        evidence: chunk.some((point) => point.evidence === true),
        from: chunk[0]!.t, samples: chunk.length,
      };
      for (const metric of metrics) {
        const values = chunk.map((point) => point[metric.key]).filter((value): value is number => typeof value === "number");
        merged[metric.key] = values.length ? values.reduce((sum, value) => sum + value, 0) : null;
      }
      grouped.push(merged);
    }
    return grouped;
  }, [rows, metrics, delta, evidenceIds, at]);

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
    tooltipTime(row.observedAt,publishedAt,false),
    ...metrics.filter((metric) => !hidden.has(metric.key)).map((metric) => historyMetricTooltip(row, metric, platform, delta)),
    !delta ? historyRatioTooltip(row, platform) : "",
  ].filter(Boolean).join(" · "), [metrics, hidden, platform, delta, publishedAt]);

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

  // В режиме «Авто» шкала строится только по показанным метрикам: первая идёт
  // слева, вторая справа. Раньше сторона выбиралась по месту метрики в полном
  // списке, и при двух показанных метриках левая шкала доставалась скрытой —
  // на экране оставалась только правая.
  const visible = metrics.filter((metric) => !hidden.has(metric.key)).slice(0, 2);
  // Сетка и линия выбранной точки привязываются к одной шкале — левой, а при
  // общем масштабе к единственной.
  const primaryAxis = scale === "shared" ? "y" : visible[0]?.key ?? "y";
  // Скрытая метрика всё равно должна ссылаться на существующую шкалу.
  const axisFor = (metric: Metric) =>
    scale === "shared" || !visible.includes(metric) ? primaryAxis : metric.key;
  const axes = scale === "shared" || !visible.length
    ? [<YAxis key="y" yAxisId="y" tickLine={false} axisLine={false} width={72} allowDecimals={false}
        tickFormatter={axisNumber} tickMargin={6} hide={!visible.length}
        label={{ value: axisTitle, angle: -90, position: "insideLeft", style: { textAnchor: "middle" }, fill: "var(--muted-foreground)" }} />]
    : visible.map((metric, index) => (
        <YAxis key={metric.key} yAxisId={metric.key} orientation={index ? "right" : "left"}
          tickLine={false} axisLine={false} width={72} allowDecimals={false}
          tickFormatter={axisNumber} tickMargin={6}
          label={{ value: metricLabel(metric, platform), angle: -90, position: index ? "insideRight" : "insideLeft", style: { textAnchor: "middle" }, fill: "var(--muted-foreground)" }} />
      ));

  const shared = {
    data,
    margin: { left: 4, right: 4, top: 8, bottom: 28 },
    onClick: (state: { activeLabel?: unknown }) => {
      const row = nearestRow(state?.activeLabel);
      if (row) onActivate(row.snapshotId);
    },
  };

  const children = (
    <>
      {/* Горизонтальные линии сетки привязаны к основной шкале: без явного
          yAxisId сетка ищет шкалу с идентификатором по умолчанию, не находит
          её и рисует одну линию по краю. Цвет задан явно, иначе контейнер
          приглушает стандартный штрих вдвое и на тёмной теме его не видно. */}
      <CartesianGrid vertical={false} yAxisId={primaryAxis} stroke="var(--border)" />
      <CollectorGapOverlay gaps={gaps} />
      <SignalOverlay markers={markers} highlight={highlight} />
      {/* Крайние столбцы упирались в шкалы и налезали на их подписи, поэтому
          у оси времени есть поля. */}
      <XAxis dataKey="t" type="number" domain={[firstAt, lastAt === firstAt ? firstAt + 1 : lastAt]}
        padding={delta ? { left: 18, right: 18 } : { left: 4, right: 4 }}
        scale="time" tickLine={false} axisLine={false} height={44} interval="preserveStartEnd"
        tick={(props) => <TimeTick {...props} rows={rows} />}
        label={{ value: "Время сохранённой точки и возраст публикации", position: "insideBottom", offset: -6, fill: "var(--muted-foreground)" }} />
      {axes}
      <ChartTooltip
        cursor={{ strokeDasharray: "4 4" }}
        content={(props) => (
          <SnapshotTooltip {...props} metrics={metrics} hidden={hidden} platform={platform} publishedAt={publishedAt} delta={delta} nearestRow={nearestRow} />
        )}
      />
      {selectedAt ? (
        <ReferenceLine x={Date.parse(selectedAt)} yAxisId={primaryAxis} stroke="var(--foreground)" strokeOpacity={0.45} strokeDasharray="3 3" />
      ) : null}
    </>
  );

  return <>

    <div
      role="img"
      tabIndex={0}
      data-chart-ready={rows.length > 0}
      aria-label={delta ? "Прирост между сохранёнными точками" : "Накопление показателей"}
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
                isAnimationActive animationDuration={420} maxBarSize={28} radius={4}>
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
          <LineChart {...shared}>
            {children}
            {metrics.map((metric) => (
              <Line key={metric.key} dataKey={metric.key} yAxisId={axisFor(metric)} hide={hidden.has(metric.key)}
                type="monotone" stroke={metric.color} strokeWidth={2.5}
                connectNulls={false} isAnimationActive animationDuration={420}
                activeDot={{ r: 5 }}
                dot={(props) => {
                  // Recharts types the per-point dot props loosely; the shape
                  // this chart supplies is narrowed at the boundary. Точка
                  // остаётся только там, где она что-то означает — на границе
                  // опубликованного сигнала; кружок на каждом замере превращал
                  // линию в пунктир и ничего не добавлял к чтению.
                  const dot = props as unknown as { cx?: number; cy?: number; payload?: { evidence?: boolean }; key?: string };
                  if (!dot.payload?.evidence) return <g key={dot.key} />;
                  return <SampleDot key={dot.key} cx={dot.cx} cy={dot.cy} fill={metric.color} evidence />;
                }}
              />
            ))}
          </LineChart>
        )}
      </ChartContainer>
    </div>
    <p id={`${chartId}-instructions`} className="sr-only">Стрелки влево и вправо выбирают сохранённую точку; Home и End — первую и последнюю. Enter или пробел открывает соответствующую строку таблицы. Escape закрывает подсказку.</p>
    <div id={`${chartId}-tooltip`} role="tooltip" aria-hidden={!tooltip} className={cn("text-muted-foreground text-sm", tooltip ? "py-2" : "sr-only")}>{tooltip}</div>
  </>;
}

/** Reads exactly what the inherited tooltip read: the sample's wall clock, each
 *  visible metric, the reaction-to-view share and whether the point is the
 *  synthetic moment of publication. */
/** Точка графика, собранная из нескольких замеров. Recharts типизирует
 *  содержимое подсказки свободно, поэтому форма сужается на границе. */
function groupedPoint(payload: unknown) {
  if (!Array.isArray(payload) || !payload.length) return null;
  const point = (payload[0] as { payload?: Record<string, unknown> } | undefined)?.payload;
  if (!point || typeof point.samples !== "number" || point.samples < 2) return null;
  if (typeof point.from !== "number" || typeof point.t !== "number") return null;
  const values: Record<string, number | null> = {};
  for (const [key, value] of Object.entries(point)) {
    if (typeof value === "number" || value === null) values[key] = value as number | null;
  }
  return { from: point.from, t: point.t, samples: point.samples, values };
}

function tooltipTime(observedAt:string,publishedAt:string,short=true) {
  const elapsed=elapsedSincePublication(publishedAt,observedAt);
  return `${short ? shortDate(observedAt) : legacyDate(observedAt)}${elapsed ? ` (${elapsed})` : ""}`;
}

function TooltipTime({ observedAt, publishedAt, rangeStart }: { observedAt:string;publishedAt:string;rangeStart?:string }) {
  const elapsed=elapsedSincePublication(publishedAt,observedAt);
  return <div className="flex items-baseline justify-between gap-3 whitespace-nowrap font-medium">
    <span>{rangeStart ? `${shortDate(rangeStart)} — ` : ""}{shortDate(observedAt)}</span>
    {elapsed ? <span className="text-muted-foreground tabular">({elapsed})</span> : null}
  </div>;
}

function SnapshotTooltip({ active, label, payload, metrics, hidden, platform, publishedAt, delta, nearestRow }: {
  active?: boolean;
  label?: unknown;
  payload?: unknown;
  metrics: Metric[];
  hidden: ReadonlySet<string>;
  platform: string;
  publishedAt: string;
  delta: boolean;
  nearestRow: (instant: unknown) => HistorySnapshot | null;
}) {
  if (!active) return null;
  // Столбец может быть группой замеров. Тогда подписи берутся из самой
  // группы: иначе высота показывала бы сумму, а подсказка — прирост одного
  // замера из неё.
  const group = groupedPoint(payload);
  if (group) {
    return (
      <div className="border-border/50 bg-background grid min-w-[12rem] gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl">
        <TooltipTime observedAt={new Date(group.t).toISOString()} rangeStart={new Date(group.from).toISOString()} publishedAt={publishedAt} />
        <div className="text-muted-foreground">Суммарно за {group.samples} сохранённых точек</div>
        {metrics.filter((metric) => !hidden.has(metric.key)).map((metric) => {
          const value = group.values[metric.key];
          return (
            <div key={metric.key} className="flex items-center gap-2">
              <span aria-hidden="true" className="size-2.5 shrink-0 rounded-[2px]" style={{ background: metric.color }} />
              <span className="text-foreground tabular">
                Прирост {noun(metric, platform)}: {value === null || value === undefined ? "—" : `${value >= 0 ? "+" : ""}${value}`}
              </span>
            </div>
          );
        })}
      </div>
    );
  }
  const row = nearestRow(label);
  if (!row) return null;
  const ratio = !delta ? historyRatioTooltip(row, platform) : "";
  return (
    <div className="border-border/50 bg-background grid min-w-[12rem] gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl">
      <TooltipTime observedAt={row.observedAt} publishedAt={publishedAt} />
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
