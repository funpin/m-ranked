import { Fragment } from "react";
import { legacyNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

type Point = { day: string; publishedCount: number; medianReactions: number | null; medianViews: number | null };

const WEEKDAY = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

/**
 * Неделя одним взглядом.
 *
 * Числа в плитках выше говорят, каков канал сейчас, но не говорят, куда он
 * движется. Здесь — семь дней: столбик показывает, сколько постов вышло в
 * день, а полоса под ним — какими они оказались по медиане реакций
 * относительно лучшего дня недели. Столбиковая диаграмма на SVG стоила бы
 * графической библиотеки на маршруте, где её сейчас нет.
 */
export function WeeklyTrend({ points }: { points: readonly Point[] }) {
  if (points.length < 2) return null;
  const maxPublished = Math.max(1, ...points.map((point) => point.publishedCount));
  const maxReactions = Math.max(1, ...points.map((point) => point.medianReactions ?? 0));
  const published = points.reduce((total, point) => total + point.publishedCount, 0);

  return (
    <section className="mt-4 rounded-lg border p-4" aria-label="Динамика за неделю">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <b className="text-sm font-semibold">Неделя</b>
        <span className="text-muted-foreground text-xs">
          {published ? <>вышло <b className="text-foreground tabular">{published}</b> публикаций за 7 дней</> : "за 7 дней публикаций не было"}
        </span>
      </div>
      <div className="mt-3 grid grid-cols-7 gap-1.5">
        {points.map((point) => {
          const date = new Date(`${point.day}T00:00:00`);
          const label = `${date.getDate()}.${String(date.getMonth() + 1).padStart(2, "0")}`;
          const reactions = point.medianReactions;
          const title = point.publishedCount
            ? `${label}: ${point.publishedCount} публикаций, медиана реакций ${legacyNumber(reactions)}, просмотров ${legacyNumber(point.medianViews)}`
            : `${label}: публикаций не было`;
          return (
            <Fragment key={point.day}>
              <div className="grid content-end gap-1" tabIndex={0} title={title}>
                <span className="sr-only">{title}</span>
                <div className="flex h-16 items-end" aria-hidden="true">
                  <span
                    className={cn("meter-fill w-full rounded-sm", point.publishedCount ? "bg-chart-2" : "bg-muted")}
                    style={{ height: `${Math.max(6, (point.publishedCount / maxPublished) * 100)}%` }}
                  />
                </div>
                <span className="bg-muted h-1 w-full overflow-hidden rounded-full" aria-hidden="true">
                  <span className="bg-chart-1 meter-fill block h-full rounded-full"
                    style={{ width: `${((reactions ?? 0) / maxReactions) * 100}%` }} />
                </span>
                <small className="text-muted-foreground text-center text-[10px] leading-none">
                  {WEEKDAY[date.getDay()]}
                </small>
              </div>
            </Fragment>
          );
        })}
      </div>
      <p className="text-muted-foreground mt-3 text-xs">
        Столбик — сколько публикаций вышло в этот день, полоса под ним — медиана реакций относительно лучшего дня недели.
      </p>
    </section>
  );
}
