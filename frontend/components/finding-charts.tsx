"use client";

import { cn } from "@/lib/utils";

/** Графики аккаунтных находок. Длина полосы — само значение от нуля, подпись —
 *  число в единицах находки: «0» читается как пустая полоса, а не как точка на
 *  непонятной шкале. Оси подписаны, цвета и сетка — как у графиков shadcn/ui,
 *  но разметкой, без Recharts: с ним окно «подробнее» открывалось на 60–80 мс
 *  дольше, а кусок анализа весил на 21 КБ больше. */

export type BarItem = { label: string; value: number; text: string; accent?: boolean; title?: string };

const ACCENT = "var(--chart-3)";
const MUTED = "var(--muted-foreground)";

/** Полосы «этот аккаунт ↔ типичный». С осью — в окне «подробнее»; без неё — в строке карточки. */
export function CompareBars({ items, title, note, max, axis = false, format }: {
  items: readonly BarItem[]; title: string; note?: string | null; max?: number; axis?: boolean;
  format?: (value: number) => string;
}) {
  const ticks = max !== undefined ? [0, max / 2, max] : niceTicks(Math.max(...items.map((item) => item.value)));
  // Нечётное число шагов — середину не подписать: ось делится пополам.
  if (ticks.length % 2 === 0) ticks.push(ticks.at(-1)! + ticks[1]!);
  const top = ticks.at(-1)!;
  const width = (value: number) => `${Math.min(100, Math.max(0, (value / top) * 100))}%`;
  return (
    <figure className="grid min-w-0 gap-1.5" data-testid="compare-bars"
      aria-label={`${title}: ${items.map((item) => `${item.label} — ${item.text}`).join(", ")}`}>
      <figcaption className="flex min-w-0 items-baseline justify-between gap-2 text-xs">
        <span className="text-muted-foreground min-w-0 truncate" title={title}>{title}</span>
        {note ? <span className="text-foreground shrink-0 text-[11px] font-medium">{note}</span> : null}
      </figcaption>
      <div className="grid min-w-0 grid-cols-[minmax(0,7rem)_minmax(0,1fr)_auto] sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1.5" aria-hidden="true">
        {items.map((item) => (
          <div key={item.label} className="contents" title={item.title}>
            <span className={cn("truncate text-[11px]", item.accent ? "text-foreground" : "text-muted-foreground")}>{item.label}</span>
            <span className="bg-muted relative h-2 min-w-0 overflow-hidden rounded-full">
              <span className="absolute inset-y-0 left-0 rounded-full"
                style={{ width: width(item.value), minWidth: item.value > 0 ? 2 : 0, background: item.accent ? ACCENT : MUTED, opacity: item.accent ? 1 : 0.55 }} />
            </span>
            {/* Цвет — у полосы; число — цветом текста: оранжевое на белом не проходит контраст AA. */}
            <b className={cn("font-heading tabular-nums text-right text-xs", item.accent ? "text-foreground" : "text-foreground/80")}>{item.text}</b>
          </div>
        ))}
        {axis && format ? <>
          <span />
          <span className="text-muted-foreground relative h-3 text-[10px] tabular-nums">
            {/* Подписаны края и середина шкалы: на телефоне пять делений слипались. */}
            {ticks.map((tick, index) => ticks.length > 3 && index % 2 && index !== ticks.length - 1 ? null : (
              <span key={tick} className={cn("absolute top-0 whitespace-nowrap", index === 0 ? "" : index === ticks.length - 1 ? "-translate-x-full" : "-translate-x-1/2")}
                style={{ left: `${(tick / top) * 100}%` }}>{tick === 0 ? "0" : format(tick)}</span>
            ))}
          </span>
          <span />
        </> : null}
      </div>
    </figure>
  );
}

/** Столбики по категориям с подписанной осью значений — для «подробнее». */
export function ColumnChart({ data, yTitle, format, testId, label }: {
  data: readonly BarItem[]; yTitle: string; format: (value: number) => string; testId: string; label: string;
}) {
  const ticks = niceTicks(Math.max(...data.map((item) => item.value)));
  const top = ticks.at(-1)!;
  // Подпись оси значений — над графиком, как заголовок шкалы.
  return (
    <figure className="grid min-w-0 gap-1" data-testid={testId}>
      <figcaption className="text-muted-foreground text-xs">{yTitle}</figcaption>
      <div role="img" aria-label={label} className="grid grid-cols-[2.75rem_minmax(0,1fr)] pt-5">
        <YTicks ticks={ticks} format={format} className="h-36" />
        <div className="relative h-36">
          <GridLines ticks={ticks} />
          <div className="absolute inset-0 flex items-end justify-around gap-3 px-2">
            {data.map((item) => {
              const height = Math.min(100, (item.value / top) * 100);
              return (
                <div key={item.label} className="relative flex h-full w-full max-w-14 items-end" title={`${item.title ?? item.label}: ${item.text}`}>
                  <span className="text-foreground absolute inset-x-0 pb-0.5 text-center text-[11px] tabular-nums whitespace-nowrap"
                    style={{ bottom: `${height}%` }}>{item.text}</span>
                  <span className="w-full rounded-t-[4px]" style={{ height: `${height}%`, minHeight: item.value > 0 ? 1 : 0,
                    background: item.accent ? ACCENT : MUTED, opacity: item.accent ? 1 : 0.45 }} />
                </div>
              );
            })}
          </div>
        </div>
        <span />
        <div className="text-muted-foreground flex justify-around gap-3 px-2 pt-1.5 text-[11px]" aria-hidden="true">
          {data.map((item) => <span key={item.label} className="w-full max-w-14 text-center whitespace-nowrap">{item.label}</span>)}
        </div>
      </div>
    </figure>
  );
}

/** Подписи делений слева от графика: положение — доля от верхнего деления. */
function YTicks({ ticks, format, className }: { ticks: readonly number[]; format: (value: number) => string; className: string }) {
  const top = ticks.at(-1)!;
  return (
    <div className={cn("text-muted-foreground relative text-[10px] tabular-nums", className)} aria-hidden="true">
      {ticks.map((tick) => (
        <span key={tick} className="absolute right-2 translate-y-1/2 whitespace-nowrap" style={{ bottom: `${(tick / top) * 100}%` }}>
          {tick === 0 ? "0" : format(tick)}
        </span>
      ))}
    </div>
  );
}

function GridLines({ ticks }: { ticks: readonly number[] }) {
  const top = ticks.at(-1)!;
  return <>{ticks.map((tick) => (
    <span key={tick} aria-hidden="true" className={cn("absolute inset-x-0 border-t", tick === 0 ? "border-border" : "border-border/60 border-dashed")}
      style={{ bottom: `${(tick / top) * 100}%` }} />
  ))}</>;
}

type Day = { day: string; observed: number; active: number; reactions: number };

/** Сутки окна: доля старых постов, получивших реакции. Серые — замеров не хватило. */
export function DailyShareChart({ days }: { days: readonly Day[] }) {
  const active = days.filter((day) => day.active > 0).length;
  const labels = new Set([0, Math.floor((days.length - 1) / 2), days.length - 1]);
  const percent = (value: number) => `${Math.round(value * 100)} %`;
  return (
    <figure className="grid gap-1.5" data-testid="daily-share-chart">
      <p className="text-muted-foreground text-xs">Доля старых постов (4–28 суток), получивших реакции за сутки</p>
      <div role="img" aria-label={`Сутки с поздними реакциями: ${active} из ${days.length}`} className="grid grid-cols-[2.75rem_minmax(0,1fr)]">
        <YTicks ticks={[0, 0.5, 1]} format={percent} className="h-28" />
        <div className="relative h-28">
          <GridLines ticks={[0, 0.5, 1]} />
          <div className="absolute inset-0 flex items-end gap-[2px]">
            {days.map((day) => {
              const share = day.observed ? day.active / day.observed : 0;
              return <span key={day.day} title={day.observed
                ? `${formatDay(day.day)}: реакции получили ${day.active} из ${day.observed} старых постов, +${day.reactions}`
                : `${formatDay(day.day)}: замеров старых постов не хватило`}
                className={cn("min-w-0 flex-1 rounded-t-[3px]", day.observed ? "bg-chart-3" : "bg-muted-foreground/20")}
                style={{ height: day.observed ? `${share * 100}%` : "100%", minHeight: day.observed && day.active ? 2 : 0 }} />;
            })}
          </div>
        </div>
        <span />
        <div className="text-muted-foreground relative h-4 pt-1 text-[10px] tabular-nums" aria-hidden="true">
          {days.map((day, index) => labels.has(index) ? (
            <span key={day.day} className={cn("absolute", index === 0 ? "" : index === days.length - 1 ? "-translate-x-full" : "-translate-x-1/2")}
              style={{ left: `${days.length > 1 ? ((index + 0.5) / days.length) * 100 : 50}%` }}>{shortDay(day.day)}</span>
          ) : null)}
        </div>
      </div>
      <figcaption className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
        <span className="inline-flex items-center gap-1.5"><span className="bg-chart-3 size-2 rounded-[2px]" />получили реакции</span>
        <span className="inline-flex items-center gap-1.5"><span className="bg-muted-foreground/30 size-2 rounded-[2px]" />замеров не хватило</span>
      </figcaption>
    </figure>
  );
}

/** Окно находки по дням: отмечены дни с волной реакций сразу на многих постах. */
export function WaveCalendar({ start, end, dates, minPosts }: { start: string; end: string; dates: readonly string[]; minPosts: number }) {
  const days: string[] = [];
  for (let time = Date.parse(`${start}T00:00:00Z`); time <= Date.parse(`${end}T00:00:00Z`) && days.length < 62; time += 86_400_000) {
    days.push(new Date(time).toISOString().slice(0, 10));
  }
  if (!days.length) return null;
  const marked = new Set(dates);
  const labels = [0, Math.floor((days.length - 1) / 2), days.length - 1];
  return (
    <figure className="grid gap-1.5" data-testid="wave-calendar">
      <div className="grid gap-[3px]" style={{ gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))` }} role="img"
        aria-label={`Дни с волной реакций: ${days.filter((day) => marked.has(day)).length} из ${days.length}`}>
        {days.map((day) => (
          <span key={day} title={`${formatDay(day)}${marked.has(day) ? ": волна реакций" : ""}`}
            className={cn("h-7 rounded-[3px]", marked.has(day) ? "bg-chart-3" : "bg-muted")} />
        ))}
      </div>
      <div className="text-muted-foreground relative h-3 text-[10px] tabular-nums" aria-hidden="true">
        {labels.map((index, position) => (
          <span key={index} className={cn("absolute top-0", position === 0 ? "left-0" : position === 1 ? "left-1/2 -translate-x-1/2" : "right-0")}>{shortDay(days[index]!)}</span>
        ))}
      </div>
      <figcaption className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
        <span className="inline-flex items-center gap-1.5"><span className="bg-chart-3 size-2 rounded-[2px]" />день, когда реакции подросли сразу у {minPosts} и больше постов</span>
        <span className="inline-flex items-center gap-1.5"><span className="bg-muted size-2 rounded-[2px]" />обычный день</span>
      </figcaption>
    </figure>
  );
}

/** Несколько чисел находки плитками — когда сравнивать не с чем. */
export function StatTiles({ items }: { items: readonly { label: string; value: string }[] }) {
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3" data-testid="finding-stats">
      {items.map((item) => (
        <div key={item.label} className="bg-muted/40 grid gap-0.5 rounded-lg border px-3 py-2">
          <dt className="text-muted-foreground text-[11px]">{item.label}</dt>
          <dd className="font-heading tabular-nums text-sm font-semibold">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Деления оси от нуля: шаг 1, 2, 2,5 или 5 × 10ⁿ, не больше четырёх шагов. */
export function niceTicks(value: number): number[] {
  if (!(value > 0)) return [0, 1];
  const raw = value / 4;
  const exponent = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((item) => item * exponent).find((item) => item >= raw - 1e-12) ?? 10 * exponent;
  const count = Math.max(1, Math.ceil(value / step - 1e-9));
  return Array.from({ length: count + 1 }, (_, index) => Number((index * step).toPrecision(12)));
}

export function shortDay(day: string) {
  const [, month, date] = day.split("-");
  return `${date}.${month}`;
}

function formatDay(day: string) {
  const [year, month, date] = day.split("-");
  return `${date}.${month}.${year}`;
}
