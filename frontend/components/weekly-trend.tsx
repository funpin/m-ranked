"use client";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import dynamic from "next/dynamic";
import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { selectedDayHref } from "@/lib/day-selection";

type Point = {
  day: string; publishedCount: number;
  medianReactions: number | null; medianViews: number | null;
  totalReactions: number | null; totalViews: number | null;
};

/** Что рисуют две линии: типичный пост или вся площадка. */
export type TrendMode = "median" | "total";

// Библиотека графиков приезжает отдельным куском, как и на странице
// публикации: в первой загрузке страницы площадки ей делать нечего.
const AccountTrendPlot = dynamic(() => import("@/components/account-trend-plot"), {
  ssr: false,
  loading: () => <Skeleton className="h-[280px] w-full sm:h-[320px]" role="status" aria-label="Загрузка графика" />,
});

const MODES: { id: TrendMode; label: string; hint: string }[] = [
  { id: "median", label: "Медианы", hint: "Каким вышел типичный пост этого дня" },
  { id: "total", label: "Всего за день", hint: "Сколько набрали все посты площадки за эти сутки" },
];

/**
 * Неделя канала: две линии и столбцы публикаций.
 *
 * Переключатель меняет, что именно показывают линии. Медиана отвечает на
 * вопрос «каким вышел типичный пост», сумма — «сколько площадка набрала»; это
 * разные вопросы, и рисовать их одновременно означало бы четыре линии на двух
 * шкалах. Сколько публикаций вышло в день, видно в обоих режимах: это опора,
 * без которой ни то ни другое не читается.
 */
export function WeeklyTrend({ points, primary, selectedDay, selectedTrend }: { points: readonly Point[]; primary: string; selectedDay?: string; selectedTrend?: TrendMode }) {
  const [mode, setMode] = useState<TrendMode>(selectedTrend ?? "median");
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const chooseMode = (next: TrendMode) => {
    setMode(next);
    router.replace(selectedDayHref(pathname, search.toString(), selectedDay, next), { scroll: false });
  };
  const published = points.reduce((total, point) => total + point.publishedCount, 0);
  const totals = mode === "total";
  return (
    <section className="grid min-w-0 content-start gap-2 rounded-lg border border-border/70 bg-background/30 p-3" aria-label="Динамика за неделю">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold leading-5">Неделя</h2>
          <span className="block text-xs leading-4 text-muted-foreground">
          {published ? <>вышло <b className="text-foreground tabular">{published}</b> публикаций за 7 дней</> : "за 7 дней публикаций не было"}
          </span>
        </div>
        <ToggleGroup aria-label="Что показывают линии" spacing={1} value={[mode]}
          className="shrink-0 rounded-lg bg-muted/70 p-0.5"
        onValueChange={(next) => {
          // Base UI reports an empty selection when the pressed item is toggled off.
          const selected = MODES.find((option) => option.id === next[0]);
          if (selected) chooseMode(selected.id);
        }}>
          {MODES.map((option) => <ToggleGroupItem key={option.id} value={option.id} title={option.hint}
            className="px-2.5 aria-pressed:bg-background aria-pressed:text-foreground aria-pressed:shadow-sm">{option.label}</ToggleGroupItem>)}
        </ToggleGroup>
      </div>
      {points.length > 1
        ? <>
            <AccountTrendPlot points={points} primary={primary} mode={mode} selectedDay={selectedDay} />
            {/* Режим указан в переключателе; легенда связывает цвет с
                показателем и шкалой и сохраняет высоту при смене режима. */}
            <ul className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground" aria-label="Легенда графика">
              {[
                { color: "var(--muted-foreground)", faded: true, name: "Публикации", side: "", description: "Публикаций в день — столбцы" },
                { color: "var(--chart-1)", name: primary === "лайков" ? "Лайки" : "Реакции", side: "слева", description: `${totals ? "Всего" : "Медиана"} ${primary} — левая шкала` },
                { color: "var(--chart-2)", name: "Просмотры", side: "справа", description: `${totals ? "Всего" : "Медиана"} просмотров — правая шкала` },
              ].map((item) => (
                <li key={item.name} className="flex items-center gap-1.5 whitespace-nowrap" aria-label={item.description} title={item.description}>
                  <span aria-hidden="true" className={cn("shrink-0 rounded-[2px]", item.faded ? "size-2 opacity-40" : "h-0.5 w-3")}
                    style={{ background: item.color }} />
                  <span>{item.name}{item.side && <> <span className="text-muted-foreground">· {item.side}</span></>}</span>
                </li>
              ))}
            </ul>
            <p className="min-h-8 text-xs leading-4 text-muted-foreground sm:min-h-4">{totals
              ? "Выберите день на графике — покажем суточный прирост."
              : "Выберите день на графике — покажем его публикации."}</p>
          </>
        : <p className="text-muted-foreground py-10 text-center text-sm">Недельного ряда ещё нет.</p>}
    </section>
  );
}
