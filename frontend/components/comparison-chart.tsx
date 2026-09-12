"use client";
import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import { useComparisonVisibility } from "./comparison-visibility";
import { cn } from "@/lib/utils";
import { formatCoverage, formatMetric } from "@/lib/format";
import type { ComparisonSeries } from "@/lib/types";
const SERIES_COLORS = Array.from({ length: 18 }, (_, index) => `var(--chart-${index + 1})`);
const ComparisonPlot = dynamic(() => import("./comparison-plot"), {
  ssr: false,
  loading: () => <Skeleton className="h-[400px] w-full sm:h-[460px] lg:h-[560px]" role="status" aria-label="Загрузка графика" />,
});

export function ComparisonChart(props: {
  series: ComparisonSeries[]; horizonHours: number; label: string;
  axisLabel?: string; metricWord?: string; maximumHour?: number;
  valueFormat?: "metric" | "percentage"; cohortKind?: "primary" | "engagement"; showLegend?: boolean;
}) {
  const { series, label, cohortKind = "primary", showLegend = true } = props;
  const { hidden, toggle } = useComparisonVisibility();
  return <div className="min-w-0" role="region" aria-label={label}>
    {showLegend ? (
        <div className="mb-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-3" role="list" aria-label="Легенда графика">
          {series.map((item, index) => {
            const isHidden = hidden.has(item.selectionId);
            const last = item.points.filter((point) => point.value !== null).at(-1);
            const cohortSize = cohortKind === "engagement" ? item.engagementCohortSize : item.primaryCohortSize;
            return (
              <div role="listitem" key={item.selectionId}>
                <button
                  type="button"
                  data-testid="comparison-legend-toggle"
                  aria-pressed={!isHidden}
                  aria-label={`${isHidden ? "Вернуть" : "Скрыть"} линию: ${item.selectionLabel}`}
                  title={last
                    ? `${formatMetric(last.value)} · выборка ${last.sampleSize} из ${cohortSize} · покрытие ${formatCoverage(last.coverage)}`
                    : "Нет доступных точек"}
                  onClick={() => toggle(item.selectionId)}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-md border bg-card px-2.5 py-2 text-left text-foreground transition-colors",
                    "hover:bg-accent focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none",
                    isHidden && "opacity-55",
                  )}
                >
                  <span
                    aria-hidden="true"
                    className="h-6 w-[3px] shrink-0 rounded-full"
                    style={{ backgroundColor: SERIES_COLORS[index % SERIES_COLORS.length] }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className={cn("block truncate font-semibold", isHidden && "line-through")}>{item.selectionLabel}</span>
                    <span className="block text-[10px] font-semibold text-muted-foreground">{cohortSize} публикаций</span>
                  </span>
                </button>
              </div>
            );
          })}
        </div>
    ) : null}
    <ComparisonPlot {...props} />
  </div>;
}
