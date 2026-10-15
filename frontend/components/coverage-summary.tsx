import { Landmark, Link2, PieChart } from "lucide-react";
import { MethodNote } from "@/components/method-note";
import type { OverviewItem } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Компактная сводка текущей страницы; основные показатели — в карточках вузов. */
export function CoverageSummary({ items, trackedInstitutions, ratedInstitutions, referenceInstitutions }: {
  items: readonly OverviewItem[]; trackedInstitutions: number | null; ratedInstitutions: number | null;
  referenceInstitutions: number;
}) {
  // В выборке — все отслеживаемые вузы, в покрытии — только участники М‑Рейтинга:
  // в каталоге есть и вузы не Минобрнауки, рейтинг их не оценивает.
  const share = ratedInstitutions === null ? null : Math.round(ratedInstitutions / referenceInstitutions * 100);

  return (
    <section className="bg-card mb-5 grid grid-cols-2 gap-3 rounded-xl border p-3 shadow-sm sm:grid-cols-3 sm:gap-4" aria-label="Выборка и покрытие вузов М‑Рейтинга">
      <Tile icon={Landmark} value={String(items.length)} label="вузов на странице" hint="Число вузов в текущей странице с учётом фильтров." />
      <Tile icon={Link2} value={trackedInstitutions === null ? "—" : String(trackedInstitutions)} label="вузов в выборке" hint="Все вузы каталога, у которых отслеживается хотя бы одна официальная соцсеть. Фильтры, поиск и страницы это число не меняют." divider />
      <div className="col-span-2 grid content-center gap-2 border-t pt-3 sm:col-span-1 sm:border-t-0 sm:border-l sm:pt-0 sm:pl-4">
        <div className="flex items-center gap-2">
          <PieChart className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
          <b className="font-heading tabular text-xl leading-none font-extrabold tracking-tight">{share === null ? "—" : `${share}%`}</b>
          <span className="text-muted-foreground text-[11px] leading-snug">покрытие вузов</span>
          <MethodNote title="Покрытие вузов М‑Рейтинга">
            <p>Число вузов М‑Рейтинга, у которых мы отслеживаем хотя бы одну официальную соцсеть, делённое на {referenceInstitutions} вузов раздела «Социальные сети» М‑Рейтинга. Вузы каталога, которых нет в М‑Рейтинге (он оценивает подведомственные Минобрнауки), в покрытие не входят. Фильтры, поиск и страницы не меняют этот показатель.</p>
            <p className="mt-2">Число вузов М‑Рейтинга обновляется только кнопкой «Обновить М‑Рейтинг» в админке.</p>
            <a href="https://m-rating.ru/#rating" target="_blank" rel="noopener noreferrer" className="mt-2 inline-block underline underline-offset-2">Официальный М‑Рейтинг</a>
          </MethodNote>
        </div>
        {share !== null ? <div className="bg-muted h-1.5 w-full overflow-hidden rounded-full" role="meter"
          aria-label="Доля отслеживаемых вузов от М‑Рейтинга" aria-valuenow={share} aria-valuemin={0} aria-valuemax={Math.max(100,share)}>
          <div className="bg-chart-2 meter-fill h-full rounded-full" style={{width:`${Math.min(100,share)}%`}} />
        </div> : null}
        <small className="text-muted-foreground tabular text-[10px]">{ratedInstitutions ?? "—"} из {referenceInstitutions} вузов</small>
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
