"use client";

import { Bar, CartesianGrid, Cell, ComposedChart, Line, ReferenceArea, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";
import { axisNumber, legacyNumber } from "@/lib/format";
import { selectedDayHref } from "@/lib/day-selection";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

type Point = {
  day: string; publishedCount: number;
  medianReactions: number | null; medianViews: number | null;
  totalReactions: number | null; totalViews: number | null;
};

/** Что рисуют две линии: типичный пост или вся площадка. */
type Mode = "median" | "total";

const WEEKDAY = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

function dayLabel(day: string, compact: boolean) {
  const date = new Date(`${day}T00:00:00`);
  const short = `${date.getDate()}.${String(date.getMonth() + 1).padStart(2, "0")}`;
  return compact ? short : `${WEEKDAY[date.getDay()]} ${short}`;
}

/** Подпись дня на оси и в подсказке; последний день ряда — сегодняшний, он ещё идёт. */
const TODAY = "сегодня";

/**
 * Неделя канала одним графиком.
 *
 * Медианы реакций и просмотров живут в разных порядках величин, поэтому у
 * каждой своя шкала — реакции слева, просмотры справа, как в режиме «Авто» на
 * странице публикации.
 *
 * Третий показатель — сколько постов вышло в день — нарисован фоновыми
 * столбцами и намеренно оставлен без подписанной шкалы: три шкалы на одном
 * графике перегружают его и заставляют читателя сверять, какая из них чья.
 * Столбцы дают форму недели, а точное число берётся из подсказки. Их шкала
 * растянута втрое, поэтому они занимают нижнюю треть поля и не спорят с
 * линиями.
 *
 * Последняя точка — сегодняшние сутки, они ещё идут: утром медианы свежих
 * постов неизбежно ниже. Поэтому сегодняшний столбец бледнее и обведён
 * пунктиром, отрезок линии к нему пунктирный, а законченные дни читаются
 * сплошной линией без него.
 */
export default function AccountTrendPlot({ points, primary, mode = "median", selectedDay }: {
  points: readonly Point[]; primary: string; mode?: Mode; selectedDay?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const totals = mode === "total";
  const reactionsKey = totals ? "totalReactions" : "medianReactions";
  const viewsKey = totals ? "totalViews" : "medianViews";
  const reactionsLabel = totals ? `Всего ${primary}` : `Медиана ${primary}`;
  const viewsLabel = totals ? "Всего просмотров" : "Медиана просмотров";
  const config: ChartConfig = {
    postsBand: { label: "Публикаций в день", color: "var(--muted-foreground)" },
    [reactionsKey]: { label: reactionsLabel, color: "var(--chart-1)" },
    [viewsKey]: { label: viewsLabel, color: "var(--chart-2)" },
  };
  // Столбцы живут на шкале просмотров, но занимают её нижнюю треть: своя,
  // третья по счёту шкала ломала отрисовку подписей у остальных двух, а
  // подписывать её всё равно было незачем — точное число даёт подсказка.
  const busiest = Math.max(1, ...points.map((point) => point.publishedCount));
  const ceiling = Math.max(1, ...points.map((point) => (totals ? point.totalViews : point.medianViews) ?? 0));
  const compact = points.length > 10;
  const last = points.length - 1;
  // Две линии на метрику: сплошная по законченным дням и пунктирный отрезок
  // от вчерашнего дня к сегодняшнему. Общая точка — вчера, поэтому линия
  // не рвётся.
  const data = points.map((point, index) => ({
    ...point,
    label: index === last ? TODAY : dayLabel(point.day, compact),
    postsBand: (point.publishedCount / busiest) * ceiling * 0.3,
    reactionsDone: index < last ? point[reactionsKey] : null,
    reactionsToday: index >= last - 1 ? point[reactionsKey] : null,
    viewsDone: index < last ? point[viewsKey] : null,
    viewsToday: index >= last - 1 ? point[viewsKey] : null,
  }));

  // Выбранный день живёт в URL: сервер построит таблицу с суточными
  // приростами, а ссылку можно перезагрузить или открыть в другой вкладке.
  // Recharts отдаёт при нажатии только номер и подпись деления, без самой
  // точки ряда, поэтому день берётся по номеру из тех же данных.
  const pick = (state: { activeIndex?: number | string | null }) => {
    const index = Number(state?.activeIndex);
    const day = Number.isInteger(index) ? data[index]?.day : undefined;
    if (day) router.replace(selectedDayHref(pathname, search.toString(), day === selectedDay ? undefined : day, mode), { scroll: false });
  };

  return (
    <ChartContainer config={config} className="h-[280px] w-full min-w-0 max-w-full aspect-auto sm:h-[320px] [&_.recharts-surface]:cursor-pointer">
      <ComposedChart data={data} margin={{ left: 4, right: 4, top: 8, bottom: 8 }} onClick={pick}>
        <CartesianGrid vertical={false} yAxisId="reactions" stroke="var(--border)" />
        {last >= 0 ? <ReferenceArea yAxisId="views" x1={TODAY} x2={TODAY} fill="var(--muted)" fillOpacity={0.45}
          ifOverflow="extendDomain" /> : null}
        <Bar yAxisId="views" dataKey="postsBand" fill="var(--muted-foreground)"
          fillOpacity={0.2} radius={[3, 3, 0, 0]} maxBarSize={compact ? 14 : 26} isAnimationActive animationDuration={420}>
          {data.map((point, index) => <Cell key={point.day} fillOpacity={index === last ? 0.08 : 0.2}
            stroke={index === last ? "var(--muted-foreground)" : undefined} strokeOpacity={0.6}
            strokeDasharray={index === last ? "3 3" : undefined} />)}
        </Bar>
        <XAxis dataKey="label" tickLine={false} axisLine={false} height={28} tickMargin={8}
          interval={compact ? "preserveStartEnd" : 0} minTickGap={compact ? 12 : 4}
          tick={(props) => <DayTick {...props} />} />
        {/* Повёрнутых подписей у осей нет: вдвоём они съедали восемьдесят
            пикселей ширины, а какая шкала чья, говорит легенда над графиком
            цветом. */}
        <YAxis yAxisId="reactions" orientation="left" tickLine={false} axisLine={false}
          width={52} allowDecimals={false} tickFormatter={axisNumber} tickMargin={6} />
        <YAxis yAxisId="views" orientation="right" tickLine={false} axisLine={false}
          width={52} allowDecimals={false} tickFormatter={axisNumber} tickMargin={6} />
        <ChartTooltip cursor={{ strokeDasharray: "4 4" }}
          content={(props) => <TrendTooltip {...props} primary={primary} mode={mode} />} />
        <Line yAxisId="reactions" dataKey="reactionsDone" name={reactionsLabel} type="monotone" stroke="var(--chart-1)"
          strokeWidth={2.5} dot={(props) => markedDot(props, selectedDay ?? null, "var(--chart-1)")} activeDot={{ r: 5 }}
          connectNulls={false} isAnimationActive animationDuration={420} />
        <Line yAxisId="reactions" dataKey="reactionsToday" type="monotone" stroke="var(--chart-1)" strokeOpacity={0.7}
          strokeWidth={2} strokeDasharray="5 4" dot={(props) => todayDot(props, last, "var(--chart-1)")} activeDot={{ r: 5 }}
          connectNulls={false} isAnimationActive animationDuration={420} legendType="none" tooltipType="none" />
        <Line yAxisId="views" dataKey="viewsDone" name={viewsLabel} type="monotone" stroke="var(--chart-2)"
          strokeWidth={2.5} dot={(props) => markedDot(props, selectedDay ?? null, "var(--chart-2)")} activeDot={{ r: 5 }}
          connectNulls={false} isAnimationActive animationDuration={420} />
        <Line yAxisId="views" dataKey="viewsToday" type="monotone" stroke="var(--chart-2)" strokeOpacity={0.7}
          strokeWidth={2} strokeDasharray="5 4" dot={(props) => todayDot(props, last, "var(--chart-2)")} activeDot={{ r: 5 }}
          connectNulls={false} isAnimationActive animationDuration={420} legendType="none" tooltipType="none" />
      </ComposedChart>
    </ChartContainer>
  );
}

function TrendTooltip({ active, payload, primary, mode }: {
  active?: boolean; payload?: unknown; primary: string; mode: Mode;
}) {
  if (!active || !Array.isArray(payload) || !payload.length) return null;
  const point = (payload[0] as { payload?: Point & { label?: string } } | undefined)?.payload;
  if (!point) return null;
  return (
    <div className="border-border/50 bg-background grid min-w-[12rem] gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl">
      <div className="font-medium">{point.label === TODAY
        ? <>Сегодня <span className="text-muted-foreground font-normal">· сутки ещё идут</span></> : point.label}</div>
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className="size-2.5 shrink-0 rounded-[2px] bg-muted-foreground/40" />
        <span className="text-foreground tabular">Публикаций в день: {point.publishedCount}</span>
      </div>
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className="size-2.5 shrink-0 rounded-[2px]" style={{ background: "var(--chart-1)" }} />
        <span className="text-foreground tabular">
          {mode === "total" ? `Всего ${primary}` : `Медиана ${primary}`}:{" "}
          {legacyNumber(mode === "total" ? point.totalReactions : point.medianReactions)}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className="size-2.5 shrink-0 rounded-[2px]" style={{ background: "var(--chart-2)" }} />
        <span className="text-foreground tabular">
          {mode === "total" ? "Всего просмотров" : "Медиана просмотров"}:{" "}
          {legacyNumber(mode === "total" ? point.totalViews : point.medianViews)}
        </span>
      </div>
    </div>
  );
}

/** Подпись сегодняшнего дня приглушена и курсивом: значения ещё растут. */
function DayTick({ x, y, payload }: { x?: number | string; y?: number | string; payload?: { value?: string } }) {
  const today = payload?.value === TODAY;
  return <text x={x} y={y} dy={12} textAnchor="middle" fontSize={12}
    fill={today ? "var(--muted-foreground)" : "var(--foreground)"} fillOpacity={today ? 1 : 0.7}
    fontStyle={today ? "italic" : undefined}>{payload?.value}</text>;
}

/** Сегодняшняя точка — полый кружок: значение неокончательное. */
function todayDot(props: unknown, last: number, color: string) {
  const { cx, cy, index, key } = props as { cx?: number; cy?: number; index?: number; key?: string };
  if (index !== last || cx === undefined || cy === undefined) return <g key={key} />;
  return <circle key={key} cx={cx} cy={cy} r={4} fill="var(--background)" stroke={color} strokeWidth={2} />;
}

/** Кружок рисуется только у выбранного дня: остальные точки читаются по линии. */
function markedDot(props: unknown, focused: string | null, color: string) {
  const { cx, cy, payload, key } = props as { cx?: number; cy?: number; key?: string; payload?: { day?: string } };
  if (!focused || payload?.day !== focused || cx === undefined || cy === undefined) {
    return <g key={key} />;
  }
  return <circle key={key} cx={cx} cy={cy} r={5} fill={color} stroke="var(--background)" strokeWidth={2} />;
}
