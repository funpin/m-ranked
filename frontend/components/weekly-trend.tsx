"use client";

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
  loading: () => <Skeleton className="h-[280px] w-full" role="status" aria-label="Загрузка графика" />,
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
    <section className="grid content-start gap-3 rounded-lg border p-4" aria-label="Динамика за неделю">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <b className="text-sm font-semibold">Неделя</b>
        <span className="text-muted-foreground text-xs">
          {published ? <>вышло <b className="text-foreground tabular">{published}</b> публикаций за 7 дней</> : "за 7 дней публикаций не было"}
        </span>
      </div>
      {/* Переключатель в том же виде, что сегменты площадок в шапке обзора:
          два состояния, подсвечено выбранное. */}
      <div role="group" aria-label="Что показывают линии"
        className="bg-muted text-muted-foreground inline-flex w-fit rounded-lg p-0.5">
        {MODES.map((option) => (
          <button key={option.id} type="button" title={option.hint}
            aria-pressed={mode === option.id}
            onClick={() => chooseMode(option.id)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              mode === option.id
                ? "bg-background text-foreground shadow-sm"
                : "bg-transparent hover:text-foreground",
            )}>
            {option.label}
          </button>
        ))}
      </div>
      {points.length > 1
        ? <>
            <AccountTrendPlot points={points} primary={primary} mode={mode} selectedDay={selectedDay} />
            {/* Легенда под графиком и всегда в три колонки на широком экране,
                в три строки на узком. Раньше она переносилась по ширине, а
                подписи в двух режимах разной длины — «медиана лайков» против
                «всего лайков», — поэтому при переключении менялось число строк
                и блок прыгал по высоте. Сетка с постоянным числом колонок этого
                не допускает: от режима высота больше не зависит. */}
            <ul className="grid grid-cols-1 gap-x-4 gap-y-1 text-xs sm:grid-cols-3" aria-hidden="true">
              {[
                { color: "var(--muted-foreground)", faded: true, name: "публикаций в день", side: "фоном" },
                { color: "var(--chart-1)", name: totals ? `всего ${primary}` : `медиана ${primary}`, side: "слева" },
                { color: "var(--chart-2)", name: totals ? "всего просмотров" : "медиана просмотров", side: "справа" },
              ].map((item) => (
                <li key={item.side} className="flex min-w-0 items-center gap-1.5">
                  <span className={cn("size-2.5 shrink-0 rounded-[2px]", item.faded && "opacity-40")}
                    style={{ background: item.color }} />
                  <span className="truncate">{item.name}</span>
                  <span className="text-muted-foreground shrink-0">· {item.side}</span>
                </li>
              ))}
            </ul>
            <p className="text-muted-foreground min-h-9 text-xs">{totals
              ? "Нажмите на день — покажем прирост каждой публикации за эти сутки в таблице ниже."
              : "Нажмите на день — покажем публикации, вышедшие в этот день."}</p>
          </>
        : <p className="text-muted-foreground py-10 text-center text-sm">Недельного ряда ещё нет.</p>}
    </section>
  );
}
