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
    <div className="compare-bars" role="list" aria-label={label}>
      {items.map((item, index) => {
        const value = metricNumber(metric(item));
        const width = value === null ? 0 : Math.max(2, value * 100 / maximum);
        const name = item.shortName || item.canonicalName;
        return (
          <div className="compare-row" role="listitem" key={item.institutionId}>
            <div className="compare-label"><span>{name}</span><strong>{formatMetric(value)}</strong></div>
            <div
              className="bar-track"
              role="img"
              aria-label={`${name}: ${formatMetric(value)} — ${label.toLocaleLowerCase("ru")}`}
            >
              <span className={`bar-fill bar-color-${index % 6}`} style={{ width: `${width}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
