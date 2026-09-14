import type { OverviewItem } from "@/lib/types";
import { cn } from "@/lib/utils";

const BUCKETS = [4, 3, 2, 1, 0] as const;
const TONE: Record<number, string> = {
  4: "bg-chart-2",
  3: "bg-chart-2/75",
  2: "bg-chart-2/55",
  1: "bg-chart-2/35",
  0: "bg-muted",
};

/**
 * Полоса покрытия над карточками общего режима.
 *
 * Сам общий режим не складывает метрики разных площадок, поэтому на карточках
 * остаются только «сколько площадок подключено» и «сколько аккаунтов». Одной
 * строкой видно, как это распределено по всей выборке на странице, — и сразу
 * понятно, где дыры в подключении.
 */
export function CoverageSummary({ items }: { items: readonly OverviewItem[] }) {
  if (!items.length) return null;
  const counts = BUCKETS.map((platforms) => ({
    platforms,
    institutions: items.filter((item) => (item.connectedPlatformCount ?? 0) === platforms).length,
  }));
  const accounts = items.reduce((total, item) => total + (item.accountCount ?? 0), 0);
  const connected = items.reduce((total, item) => total + (item.connectedPlatformCount ?? 0), 0);
  const share = Math.round((connected / (items.length * 4)) * 100);

  return (
    <section className="bg-card mb-4 rounded-xl border p-4" aria-label="Покрытие площадок на этой странице">
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <Stat value={String(items.length)} label="вузов на странице" />
        <Stat value={`${share}%`} label="площадок подключено" />
        <Stat value={String(accounts)} label="аккаунтов добавлено" />
      </div>
      <div className="bg-muted mt-3 flex h-2 w-full overflow-hidden rounded-full" aria-hidden="true">
        {counts.filter((bucket) => bucket.institutions).map((bucket) => (
          <span
            key={bucket.platforms}
            className={cn("meter-fill h-full", TONE[bucket.platforms])}
            style={{ width: `${(bucket.institutions / items.length) * 100}%` }}
          />
        ))}
      </div>
      <ul className="text-muted-foreground mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {counts.filter((bucket) => bucket.institutions).map((bucket) => (
          <li key={bucket.platforms} className="flex items-center gap-1.5">
            <span className={cn("size-2 shrink-0 rounded-full", TONE[bucket.platforms])} aria-hidden="true" />
            {bucket.platforms === 0 ? "без площадок" : `${bucket.platforms} из 4`}: <b className="text-foreground tabular">{bucket.institutions}</b>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <span className="flex items-baseline gap-2">
      <b className="font-heading tabular text-xl leading-none font-extrabold tracking-tight">{value}</b>
      <small className="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">{label}</small>
    </span>
  );
}
