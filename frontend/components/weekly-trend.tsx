"use client";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
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

/** Период графика: семь или тридцать полных дней и сегодняшние сутки. */
type Span = 7 | 30;
const SPANS: { id: Span; label: string; hint: string }[] = [
  { id: 7, label: "7 д", hint: "Семь полных дней и сегодня" },
  { id: 30, label: "30 д", hint: "Тридцать полных дней и сегодня" },
];

const periodDate = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", timeZone: "UTC" });
const period = (points: readonly Point[]) => points.length
  ? `${periodDate.format(new Date(`${points[0]!.day}T00:00:00Z`))} — сегодня` : "";

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
export function WeeklyTrend({ points, primary, selectedDay, selectedTrend, accountId }: { points: readonly Point[]; primary: string; selectedDay?: string; selectedTrend?: TrendMode; accountId?: string }) {
  const [mode, setMode] = useState<TrendMode>(selectedTrend ?? "median");
  const [span, setSpan] = useState<Span>(7);
  // Месяц приходит отдельным запросом только по нажатию: карточка аккаунта
  // несёт неделю, а месячный ряд нужен не каждому читателю.
  const [month, setMonth] = useState<readonly Point[] | null>(null);
  const [monthFailed, setMonthFailed] = useState(false);
  useEffect(() => {
    if (span !== 30 || month || !accountId) return;
    const controller = new AbortController();
    fetch(`/api/v1/accounts/${accountId}/daily-series?days=30`, { headers: { accept: "application/json" }, signal: controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(String(response.status))))
      .then((body: { points: Point[] }) => setMonth(body.points))
      .catch(() => { if (!controller.signal.aborted) { setMonthFailed(true); setSpan(7); } });
    return () => controller.abort();
  }, [span, month, accountId]);
  const shown = span === 30 && month ? month : points;
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const chooseMode = (next: TrendMode) => {
    setMode(next);
    router.replace(selectedDayHref(pathname, search.toString(), selectedDay, next), { scroll: false });
  };
  // Сегодняшние сутки ещё идут: публикации за полные дни и за сегодня — раздельно.
  const today = shown.at(-1);
  const published = shown.slice(0, -1).reduce((total, point) => total + point.publishedCount, 0);
  const days = Math.max(0, shown.length - 1);
  const totals = mode === "total";
  return (
    <section className="grid min-w-0 content-start gap-2 rounded-lg border border-border/70 bg-background/30 p-3" aria-label="Динамика за неделю">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold leading-5">{span === 30 ? "Месяц" : "Неделя"}
            <span className="text-muted-foreground ml-1.5 text-xs font-normal">{period(shown)}</span></h2>
          <span className="block text-xs leading-4 text-muted-foreground">
          {published ? <>вышло <b className="text-foreground tabular">{published}</b> публикаций за {days} дней</> : `за ${days} дней публикаций не было`}
          {today ? <>, сегодня — <b className="text-foreground tabular">{today.publishedCount}</b></> : null}
          {monthFailed ? " · месячный ряд временно недоступен" : null}
          </span>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
        {accountId ? <ToggleGroup aria-label="Период графика" spacing={1} value={[String(span)]}
          className="shrink-0 rounded-lg bg-muted/70 p-0.5"
          onValueChange={(next) => {
            const selected = SPANS.find((option) => String(option.id) === next[0]);
            if (selected) setSpan(selected.id);
          }}>
          {SPANS.map((option) => <ToggleGroupItem key={option.id} value={String(option.id)} title={option.hint}
            className="px-2.5 aria-pressed:bg-background aria-pressed:text-foreground aria-pressed:shadow-sm">{option.label}</ToggleGroupItem>)}
        </ToggleGroup> : null}
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
      </div>
      {shown.length > 1
        ? <>
            {span === 30 && !month ? <Skeleton className="h-[280px] w-full sm:h-[320px]" role="status" aria-label="Загрузка месячного ряда" />
              : <AccountTrendPlot points={shown} primary={primary} mode={mode} selectedDay={selectedDay} />}
            {/* Режим указан в переключателе; легенда связывает цвет с
                показателем и шкалой и сохраняет высоту при смене режима. */}
            <ul className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground" aria-label="Легенда графика">
              {[
                { color: "var(--muted-foreground)", faded: true, name: "Публикации", side: "", description: "Публикаций в день — столбцы; сегодняшний столбец пунктирный, сутки ещё идут" },
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
