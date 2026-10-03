import { Landmark, Link2, PieChart } from "lucide-react";
import { MethodNote } from "@/components/method-note";
import type { OverviewItem } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Компактная сводка текущей страницы; основные показатели — в карточках вузов. */
export function CoverageSummary({ items }: { items: readonly OverviewItem[] }) {
  if (!items.length) return null;
  const counts = [4, 3, 2, 1, 0].map((platforms) => ({
    platforms,
    institutions: items.filter((item) => (item.connectedPlatformCount ?? 0) === platforms).length,
  })).filter((bucket) => bucket.institutions);
  const accounts = items.reduce((total, item) => total + (item.accountCount ?? 0), 0);
  const connected = items.reduce((total, item) => total + (item.connectedPlatformCount ?? 0), 0);
  const share = Math.round((connected / (items.length * 4)) * 100);

  return (
    <section className="bg-card mb-5 grid grid-cols-2 gap-3 rounded-xl border p-3 shadow-sm sm:grid-cols-3 sm:gap-4" aria-label="Покрытие площадок на этой странице">
      <Tile icon={Landmark} value={String(items.length)} label="вузов на странице" hint="Число вузов в текущей странице с учётом фильтров." />
      <Tile icon={Link2} value={String(accounts)} label="аккаунтов в выборке" hint="Число официальных аккаунтов вузов на этой странице, включая отключённые." divider />
      <div className="col-span-2 grid content-center gap-2 border-t pt-3 sm:col-span-1 sm:border-t-0 sm:border-l sm:pt-0 sm:pl-4">
        <div className="flex items-center gap-2">
          <PieChart className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
          <b className="font-heading tabular text-xl leading-none font-extrabold tracking-tight">{share}%</b>
          <span className="text-muted-foreground text-[11px] leading-snug">покрытие соцсетей</span>
          <MethodNote title="Покрытие соцсетей на этой странице">
            <p>Подключено {connected} из {items.length * 4} возможных площадок. Для каждого вуза учитываются только соцсети с включённым отслеживанием; несколько аккаунтов одной соцсети считаются одной площадкой.</p>
            <ul className="mt-2 grid gap-1">{counts.map(bucket => <li key={bucket.platforms}>{bucket.platforms} из 4 площадок: {bucket.institutions} вузов</li>)}</ul>
          </MethodNote>
        </div>
        <div className="bg-muted h-1.5 w-full overflow-hidden rounded-full" role="meter"
          aria-label="Доля подключённых соцсетей на этой странице" aria-valuenow={share} aria-valuemin={0} aria-valuemax={100}>
          <div className="bg-chart-2 meter-fill h-full rounded-full" style={{width:`${share}%`}} />
        </div>
      </div>
    </section>
  );
}

function Tile({ icon: Icon, value, label, hint, divider = false }: {
  icon: typeof Landmark; value: string; label: string; hint: string; divider?: boolean;
}) {
  return (
    <div className={cn("flex items-center gap-2.5", divider && "border-l pl-3 sm:pl-4")} title={hint}>
      <Icon className="text-muted-foreground size-4" aria-hidden="true" />
      <div className="min-w-0">
        <b className="font-heading tabular block text-xl leading-none font-extrabold tracking-tight">{value}</b>
        <span className="text-muted-foreground mt-1 block text-[11px] leading-snug">{label}</span>
      </div>
    </div>
  );
}
