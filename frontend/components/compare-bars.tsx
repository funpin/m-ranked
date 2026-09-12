import { formatMetric } from "@/lib/format";
import { metricNumber } from "@/lib/params";
import type { MetricValue, OverviewItem } from "@/lib/types";

export function CompareBars({
  items,
  metric,
  label,
}: {
  items: OverviewItem[];
  metric: (item: OverviewItem) => MetricValue;
  label: string;
}) {
  const values = items.map((item) => metricNumber(metric(item)) ?? 0);
  const maximum = Math.max(1, ...values);
  return (
    <div className="grid gap-4" role="list" aria-label={label}>
      {items.map((item, index) => {
        const value = metricNumber(metric(item));
        const width = value === null ? 0 : Math.max(2, value * 100 / maximum);
        const name = item.shortName || item.canonicalName;
        return (
          <div className="grid gap-2" role="listitem" key={item.institutionId}>
            <div className="flex items-baseline justify-between gap-3 text-sm"><span>{name}</span><strong>{formatMetric(value)}</strong></div>
            <div
              className="h-2 overflow-hidden rounded-full bg-muted"
              role="img"
              aria-label={`${name}: ${formatMetric(value)} — ${label.toLocaleLowerCase("ru")}`}
            >
              <span className="block h-full rounded-full" style={{ width: `${Math.min(100, Math.max(0, width))}%`, backgroundColor: `var(--chart-${index % 18 + 1})` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
