import { comparisonPointSegments } from "@/lib/comparison-chart-data";
import { formatCoverage, formatMetric, formatPercentage } from "@/lib/format";
import type { ComparisonSeries } from "@/lib/types";

const COLORS = ["#6aa7ff", "#5fd2a2", "#f0b65a", "#b69cff", "#52c8db", "#ff7f98"];
const WIDTH = 920;
const HEIGHT = 340;
const LEFT = 66;
const RIGHT = 24;
const TOP = 24;
const BOTTOM = 46;

export function ComparisonChart({
  series,
  horizonHours,
  label,
  valueFormat = "metric",
  cohortKind = "primary",
}: {
  series: ComparisonSeries[];
  horizonHours: number;
  label: string;
  valueFormat?: "metric" | "percentage";
  cohortKind?: "primary" | "engagement";
}) {
  const prepared = series.map((item) => {
    const pointSegments = comparisonPointSegments(item.points);
    return { ...item, pointSegments, numericPoints: pointSegments.flat() };
  });
  const maximum = Math.max(1, ...prepared.flatMap((item) => item.numericPoints.map((point) => point.numericValue)));
  const plotWidth = WIDTH - LEFT - RIGHT;
  const plotHeight = HEIGHT - TOP - BOTTOM;
  const x = (hour: number) => LEFT + Math.min(horizonHours, Math.max(0, hour)) * plotWidth / horizonHours;
  const y = (value: number) => TOP + (1 - Math.max(0, value) / maximum) * plotHeight;
  const yTicks = [0, 0.25, 0.5, 0.75, 1];
  const xTicks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div
      className="comparison-chart-wrap"
      role="region"
      aria-label="Прокручиваемая область графика"
      tabIndex={0}
    >
      <svg className="comparison-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`${label}: почасовые кривые, ${series.length} рядов`}>
        <title>{label}</title>
        {yTicks.map((ratio) => {
          const position = TOP + ratio * plotHeight;
          return (
            <g key={`y-${ratio}`}>
              <line className="chart-grid-line" x1={LEFT} x2={WIDTH - RIGHT} y1={position} y2={position} />
              <text className="chart-axis-label" x={LEFT - 10} y={position + 4} textAnchor="end">
                {valueFormat === "percentage"
                  ? formatPercentage(maximum * (1 - ratio))
                  : formatMetric(maximum * (1 - ratio), true)}
              </text>
            </g>
          );
        })}
        {xTicks.map((ratio) => {
          const hour = Math.round(horizonHours * ratio);
          const position = x(hour);
          return (
            <g key={`x-${ratio}`}>
              <line className="chart-tick" x1={position} x2={position} y1={HEIGHT - BOTTOM} y2={HEIGHT - BOTTOM + 6} />
              <text className="chart-axis-label" x={position} y={HEIGHT - 17} textAnchor="middle">{hour} ч</text>
            </g>
          );
        })}
        {prepared.flatMap((item, index) => item.pointSegments.map((points, segmentIndex) => {
          const path = points.map((point, pointIndex) => `${pointIndex ? "L" : "M"}${x(point.hourOffset).toFixed(2)},${y(point.numericValue).toFixed(2)}`).join(" ");
          return path ? <path key={`${item.selectionId}-${segmentIndex}`} d={path} fill="none" stroke={COLORS[index % COLORS.length]} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /> : null;
        }))}
      </svg>
      <div className="chart-legend" role="list" aria-label="Легенда графика">
        {prepared.map((item, index) => {
          const last = item.numericPoints.at(-1);
          const cohortSize = cohortKind === "engagement"
            ? item.engagementCohortSize
            : item.primaryCohortSize;
          return (
            <div className="chart-legend-item" role="listitem" key={item.selectionId}>
              <span className="chart-swatch" style={{ backgroundColor: COLORS[index % COLORS.length] }} aria-hidden="true" />
              <span><strong>{item.selectionLabel}</strong><small>{last ? `${valueFormat === "percentage" ? formatPercentage(last.numericValue) : formatMetric(last.numericValue)} · выборка ${last.sampleSize} из ${cohortSize} · покрытие ${formatCoverage(last.coverage)}` : `нет доступных точек · выборка ${cohortSize}`}</small></span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
