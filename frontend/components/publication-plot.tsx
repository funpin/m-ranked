"use client";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, XAxis, YAxis, usePlotArea, useXAxisScale } from "recharts";
import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";
import { axisNumber, legacyDate } from "@/lib/format";
import { elapsedSincePublication } from "@/lib/history-data";
import { historyMetricValue, historyMetricTooltip, historyRatioTooltip, metricLabel, metricNoun as noun, type HistoryMetric as Metric } from "@/lib/history-metrics";
import { cn } from "@/lib/utils";
import { PatternIcon } from "@/components/anomaly-icons";
import { clusterPixelMarks, gapPresentation, mergePixelIntervals } from "@/lib/plot-density";
import type { CollectorGap, HistorySnapshot } from "@/lib/types";
import type { SignalMarker } from "@/lib/anomaly";
function shortDate(value:string) {return legacyDate(value).replace(/\.\d{4},/, ",");}

/** Больше этого числа столбцов прироста на экране уже не различить: при
 *  ширине графика около девятисот точек каждый столбец становится тоньше
 *  волоса, и картинка перестаёт читаться. */
const MAX_BARS = 56;
const GAP_MERGE_DISTANCE_PX = 3;

/** Draw confirmed collector gaps as subpaths of one SVG element.
 *
 * A noisy account can have hundreds of short gaps. Rendering each one as a
 * Recharts ReferenceArea created thousands of React/SVG nodes across the two
 * plots and made the whole page expensive to paint while scrolling. Gaps whose
 * visible separation is three pixels or less are merged at the current scale:
 * zooming in separates them again. The textual count and duration remain exact.
 * One path keeps the overlay at one DOM node per chart. */
function CollectorGapOverlay({ gaps }: { gaps: readonly CollectorGap[] }) {
  const scale = useXAxisScale();
  const plot = usePlotArea();
  const overlay = useMemo(() => {
    if (!scale || !plot || !gaps.length) return { path: "", blocks: 0, mode: "bands" as const };
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
    const blocks = mergePixelIntervals(projected, GAP_MERGE_DISTANCE_PX);
    const mode = gapPresentation(blocks, plot.width);
    const path = blocks.map(({left,right}) =>
      `M${left.toFixed(2)},${minY.toFixed(2)}H${right.toFixed(2)}V${(mode === "rail" ? minY + 4 : maxY).toFixed(2)}H${left.toFixed(2)}Z`,
    ).join("");
    return {path,blocks:blocks.length,mode};
  }, [gaps, plot, scale]);
  return overlay.path ? <path className="collector-gap" data-gap-blocks={overlay.blocks} data-gap-count={gaps.length} data-gap-mode={overlay.mode}
    d={overlay.path} fill="var(--destructive)" fillOpacity={overlay.mode === "rail" ? 0.8 : 0.11}
    stroke="var(--destructive)" strokeOpacity={overlay.mode === "rail" ? 0 : 0.35} strokeWidth={1} pointerEvents="none" /> : null;
}

const SIGNAL_COLORS: Record<SignalMarker["tone"], string> = {
  priority: "var(--destructive)",
  review: "var(--chart-3)",
};
const SIGNAL_RANK: Record<SignalMarker["tone"], number> = {
  priority: 3, review: 2,
};

/** Pattern glyphs are the primary marks. Nearby intervals share a mark at the
 * current pixel scale; their exact identity stays in the title and flat list. */
function SignalOverlay({ markers, highlight }: { markers: readonly SignalMarker[]; highlight?: string }) {
  const scale = useXAxisScale();
  const plot = usePlotArea();
  if (!scale || !plot || !markers.length) return null;
  const ranges = markers.flatMap((marker) => {
      const from = scale(marker.from), to = scale(marker.to);
      if (from === undefined || to === undefined) return [];
      const left = Math.max(plot.x, Math.min(from, to));
      const right = Math.min(plot.x + plot.width, Math.max(from, to, Math.min(from, to) + 2));
      return Number.isFinite(left) && Number.isFinite(right) && right > left
        ? [{ left, right, x: (left + right) / 2, marker }] : [];
    }).sort((a, b) => a.left - b.left || a.right - b.right);
  const groups = clusterPixelMarks(ranges, 25);
  return <g className="signal-markers" data-signal-count={markers.length} data-signal-groups={groups.length}>
    {groups.map(({ x, marks }) => {
      const lead = [...marks].sort((a, b) => SIGNAL_RANK[b.marker.tone] - SIGNAL_RANK[a.marker.tone])[0]!.marker;
      const color = SIGNAL_COLORS[lead.tone];
      const left = Math.min(...marks.map((mark) => mark.left));
      const right = Math.max(...marks.map((mark) => mark.right));
      const selected = marks.some((mark) => mark.marker.id === highlight);
      const label = marks.map((mark) => mark.marker.title).join("; ");
      return <g key={marks.map((mark) => mark.marker.id).join("-")} data-signal-marker={marks.length}
        role="img" aria-label={`${marks.length > 1 ? `${marks.length} признака: ` : "Признак: "}${label}`}>
        <title>{label}</title>
        <rect data-signal-band="" x={left} y={plot.y} width={Math.max(2, right - left)} height={plot.height}
          fill={color} fillOpacity={selected ? 0.13 : 0.055} pointerEvents="none" />
        {selected ? <rect data-signal-highlight="" x={left} y={plot.y} width={Math.max(2, right - left)} height={plot.height}
          fill="none" stroke={color} strokeOpacity={0.65} strokeWidth={1.5} pointerEvents="none" /> : null}
        <circle cx={x} cy={plot.y - 13} r={10} fill="var(--background)" stroke={color} strokeWidth={2} pointerEvents="none" />
        <PatternIcon pattern={lead.pattern} x={x - 6} y={plot.y - 19} width={12} height={12}
          color={color} strokeWidth={2.2} pointerEvents="none" />
        {marks.length > 1 ? <text x={x + 11} y={plot.y - 19} fill={color} fontSize={9} fontWeight={700}
          pointerEvents="none">+{marks.length - 1}</text> : null}
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

// Всё, что уходит в recharts, держится одной ссылкой между отрисовками.
// recharts 3 переносит настройки осей, подсказки и точек в свой store
// эффектами: новый объект на каждую отрисовку — новая запись в store и новая
// отрисовка. Пока ползунок масштаба двигается, это превращалось в каскад и
// заканчивалось ошибкой React #185 («Maximum update depth exceeded»).
const ACTIVE_DOT = { r: 5 } as const;
const TOOLTIP_CURSOR = { strokeDasharray: "4 4" } as const;
const LABEL_STYLE = { textAnchor: "middle" } as const;
const BAR_PADDING = { left: 18, right: 18 } as const;
const LINE_PADDING = { left: 4, right: 4 } as const;
const renderTimeTick = (props: Parameters<typeof TimeTick>[0]) => <TimeTick {...props} />;

/** Keep the axis to one compact line; sample age stays in the chart tooltip. */
function TimeTick({ x, y, payload, index, visibleTicksCount }: {
  x?: number | string; y?: number | string; payload?: { value?: number };
  index?: number; visibleTicksCount?: number;
}) {
  const value = payload?.value;
  if (x === undefined || y === undefined || typeof value !== "number") return null;
  const anchor: "start" | "middle" | "end" = index === 0 ? "start" : index === (visibleTicksCount ?? 0) - 1 ? "end" : "middle";
  return (
    <text x={x} y={Number(y) + 12} textAnchor={anchor} fill="var(--muted-foreground)" fontSize={11}>
      {shortDate(new Date(value).toISOString())}
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
  const domain = useMemo(() => [firstAt, lastAt === firstAt ? firstAt + 1 : lastAt], [firstAt, lastAt]);

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
  const visible = useMemo(() => metrics.filter((metric) => !hidden.has(metric.key)).slice(0, 2), [metrics, hidden]);
  // Сетка и линия выбранной точки привязываются к одной шкале — левой, а при
  // общем масштабе к единственной.
  const primaryAxis = scale === "shared" ? "y" : visible[0]?.key ?? "y";
  // Скрытая метрика всё равно должна ссылаться на существующую шкалу.
  const axisFor = (metric: Metric) =>
    scale === "shared" || !visible.includes(metric) ? primaryAxis : metric.key;
  const axes = useMemo(() => scale === "shared" || !visible.length
    ? [<YAxis key="y" yAxisId="y" tickLine={false} axisLine={false} width={72} allowDecimals={false}
        tickFormatter={axisNumber} tickMargin={6} hide={!visible.length}
        label={{ value: axisTitle, angle: -90, position: "insideLeft", style: LABEL_STYLE, fill: "var(--muted-foreground)" }} />]
    : visible.map((metric, index) => (
        <YAxis key={metric.key} yAxisId={metric.key} orientation={index ? "right" : "left"}
          tickLine={false} axisLine={false} width={72} allowDecimals={false}
          tickFormatter={axisNumber} tickMargin={6}
          label={{ value: metricLabel(metric, platform), angle: -90, position: index ? "insideRight" : "insideLeft", style: LABEL_STYLE, fill: "var(--muted-foreground)" }} />
      )), [scale, visible, axisTitle, platform]);

  const margin = useMemo(() => ({ left: 4, right: 4, top: markers.length ? 30 : 8, bottom: 8 }), [markers.length]);
  const onClick = useCallback((state: { activeLabel?: unknown }, event: ReactMouseEvent<SVGGraphicsElement>) => {
    let row = nearestRow(state?.activeLabel);
    // Recharts has no active label when the click lands between sparse
    // points. Resolve that click by its position in the visible time axis.
    if (!row && rows.length) {
      const bounds = event.currentTarget.getBoundingClientRect();
      const left = bounds.left + 76;
      const width = Math.max(1, bounds.width - 80 - (scale === "auto" && visible.length > 1 ? 72 : 0));
      const fraction = Math.max(0, Math.min(1, (event.clientX - left) / width));
      row = nearestRow(firstAt + fraction * (lastAt - firstAt));
    }
    if (row) onActivate(row.snapshotId);
  }, [nearestRow, rows.length, scale, visible.length, firstAt, lastAt, onActivate]);
  const tooltipContent = useCallback((props: { active?: boolean; label?: unknown; payload?: unknown }) => (
    <SnapshotTooltip {...props} metrics={metrics} hidden={hidden} platform={platform} publishedAt={publishedAt} delta={delta} nearestRow={nearestRow} />
  ), [metrics, hidden, platform, publishedAt, delta, nearestRow]);
  // Точка остаётся только там, где она что-то означает — на границе
  // опубликованного сигнала; кружок на каждом замере превращал линию в пунктир.
  const dots = useMemo(() => new Map(metrics.map((metric) => [metric.key, (props: unknown) => {
    // Recharts types the per-point dot props loosely; the shape this chart
    // supplies is narrowed at the boundary.
    const dot = props as { cx?: number; cy?: number; payload?: { evidence?: boolean }; key?: string };
    if (!dot.payload?.evidence) return <g key={dot.key} />;
    return <SampleDot key={dot.key} cx={dot.cx} cy={dot.cy} fill={metric.color} evidence />;
  }])), [metrics]);

  const shared = { data, margin, onClick };

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
      <XAxis dataKey="t" type="number" domain={domain}
        padding={delta ? BAR_PADDING : LINE_PADDING}
        scale="time" tickLine={false} axisLine={false} height={30} tickCount={3} minTickGap={80} interval="preserveStartEnd"
        tick={renderTimeTick} />
      {axes}
      <ChartTooltip cursor={TOOLTIP_CURSOR} content={tooltipContent} />
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
                activeDot={ACTIVE_DOT}
                dot={dots.get(metric.key)}
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
