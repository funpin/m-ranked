import { Landmark, Link2, PieChart } from "lucide-react";
import type { OverviewItem } from "@/lib/types";
import { cn } from "@/lib/utils";

const BUCKETS = [4, 3, 2, 1, 0] as const;
const TONE: Record<number, string> = {
  4: "bg-chart-2",
  3: "bg-chart-2/75",
  2: "bg-chart-2/55",
  1: "bg-chart-2/35",
  0: "bg-muted-foreground/30",
};

/**
 * Покрытие площадок над карточками общего режима.
 *
 * Раньше это была одна широкая полоса с тремя числами в строку и легендой
 * под ней — читалось как обрывок таблицы. Теперь три равноправные плитки той
 * же формы, что и карточки вуза под ними: два счётчика и распределение, в
 * котором сразу видно, у скольких вузов подключены не все площадки.
 */
export function CoverageSummary({ items }: { items: readonly OverviewItem[] }) {
  if (!items.length) return null;
  const counts = BUCKETS.map((platforms) => ({
    platforms,
    institutions: items.filter((item) => (item.connectedPlatformCount ?? 0) === platforms).length,
  })).filter((bucket) => bucket.institutions);
  const accounts = items.reduce((total, item) => total + (item.accountCount ?? 0), 0);
  const connected = items.reduce((total, item) => total + (item.connectedPlatformCount ?? 0), 0);
  const share = Math.round((connected / (items.length * 4)) * 100);

  return (
    <section className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Покрытие площадок на этой странице">
      <Tile icon={Landmark} value={String(items.length)} label="вузов на странице" hint="Столько карточек попало в текущую выборку." />
      <Tile icon={Link2} value={String(accounts)} label="аккаунтов добавлено" hint="Сумма подключённых аккаунтов по всем площадкам." />
      <div className="bg-card rounded-xl border p-4 shadow-sm">
        <div className="flex items-baseline gap-2">
          <PieChart className="text-muted-foreground size-4 shrink-0 self-center" aria-hidden="true" />
          <b className="font-heading tabular text-2xl leading-none font-extrabold tracking-tight">{share}%</b>
          <small className="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">площадок подключено</small>
        </div>
        <div className="bg-muted mt-3 flex h-2 w-full overflow-hidden rounded-full" aria-hidden="true">
          {counts.map((bucket) => (
            <span key={bucket.platforms} className={cn("meter-fill h-full", TONE[bucket.platforms])}
              style={{ width: `${(bucket.institutions / items.length) * 100}%` }} />
          ))}
        </div>
        <ul className="text-muted-foreground mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {counts.map((bucket) => (
            <li key={bucket.platforms} className="flex items-center gap-1.5">
              <span className={cn("size-2 shrink-0 rounded-full", TONE[bucket.platforms])} aria-hidden="true" />
              {bucket.platforms === 0 ? "без площадок" : `${bucket.platforms} из 4`}: <b className="text-foreground tabular">{bucket.institutions}</b>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Tile({ icon: Icon, value, label, hint }: {
  icon: typeof Landmark; value: string; label: string; hint: string;
}) {
  return (
    <div className="bg-card flex flex-col justify-between rounded-xl border p-4 shadow-sm" title={hint}>
      <Icon className="text-muted-foreground size-4" aria-hidden="true" />
      <div className="mt-3">
        <b className="font-heading tabular block text-2xl leading-none font-extrabold tracking-tight">{value}</b>
        <small className="text-muted-foreground mt-1 block text-[10px] font-medium tracking-wide uppercase">{label}</small>
      </div>
    </div>
  );
}
