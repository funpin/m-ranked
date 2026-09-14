"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";

type Point = { day: string; publishedCount: number; medianReactions: number | null; medianViews: number | null };

// Библиотека графиков приезжает отдельным куском, как и на странице
// публикации: в первой загрузке страницы площадки ей делать нечего.
const AccountTrendPlot = dynamic(() => import("@/components/account-trend-plot"), {
  ssr: false,
  loading: () => <Skeleton className="h-[280px] w-full" role="status" aria-label="Загрузка графика" />,
});

/**
 * Неделя канала: медианы реакций и просмотров по дням.
 *
 * Числа слева говорят, каков канал сейчас; график — куда он движется. Ряд
 * приходит всегда полным, поэтому день без публикаций виден как провал, а не
 * как разрыв.
 */
export function WeeklyTrend({ points, primary }: { points: readonly Point[]; primary: string }) {
  const published = points.reduce((total, point) => total + point.publishedCount, 0);
  return (
    <section className="grid content-start gap-3 rounded-lg border p-4" aria-label="Динамика за неделю">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <b className="text-sm font-semibold">Неделя</b>
        <span className="text-muted-foreground text-xs">
          {published ? <>вышло <b className="text-foreground tabular">{published}</b> публикаций за 7 дней</> : "за 7 дней публикаций не было"}
        </span>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-hidden="true">
        <span className="flex items-center gap-1.5">
          <span className="bg-muted-foreground/40 size-2.5 rounded-[2px]" />
          публикаций в день <span className="text-muted-foreground">· фоном</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[2px]" style={{ background: "var(--chart-1)" }} />
          медиана {primary} <span className="text-muted-foreground">· слева</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[2px]" style={{ background: "var(--chart-2)" }} />
          медиана просмотров <span className="text-muted-foreground">· справа</span>
        </span>
      </div>
      {points.length > 1
        ? <>
            <AccountTrendPlot points={points} primary={primary} />
            <p className="text-muted-foreground text-xs">Нажмите на день — покажем публикации этого дня в таблице ниже.</p>
          </>
        : <p className="text-muted-foreground py-10 text-center text-sm">Недельного ряда ещё нет.</p>}
    </section>
  );
}
