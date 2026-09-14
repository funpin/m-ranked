"use client";

import { Bar, CartesianGrid, ComposedChart, Line, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";
import { axisNumber, legacyNumber } from "@/lib/format";
import { toggleFocusedDay, useFocusedDay } from "@/lib/day-focus";

type Point = { day: string; publishedCount: number; medianReactions: number | null; medianViews: number | null };

const WEEKDAY = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

function dayLabel(day: string) {
  const date = new Date(`${day}T00:00:00`);
  return `${WEEKDAY[date.getDay()]} ${date.getDate()}.${String(date.getMonth() + 1).padStart(2, "0")}`;
}

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
 */
export default function AccountTrendPlot({ points, primary }: { points: readonly Point[]; primary: string }) {
  const config: ChartConfig = {
    postsBand: { label: "Публикаций в день", color: "var(--muted-foreground)" },
    medianReactions: { label: `Медиана ${primary}`, color: "var(--chart-1)" },
    medianViews: { label: "Медиана просмотров", color: "var(--chart-2)" },
  };
  // Столбцы живут на шкале просмотров, но занимают её нижнюю треть: своя,
  // третья по счёту шкала ломала отрисовку подписей у остальных двух, а
  // подписывать её всё равно было незачем — точное число даёт подсказка.
  const busiest = Math.max(1, ...points.map((point) => point.publishedCount));
  const ceiling = Math.max(1, ...points.map((point) => point.medianViews ?? 0));
  const data = points.map((point) => ({
    ...point,
    label: dayLabel(point.day),
    postsBand: (point.publishedCount / busiest) * ceiling * 0.3,
  }));

  // Нажатие по дню переносит к публикациям этого дня в таблице ниже — так же,
  // как точка на графике поста переносит к своему замеру.
  const focused = useFocusedDay();
  // Recharts отдаёт при нажатии только номер и подпись деления, без самой
  // точки ряда, поэтому день берётся по номеру из тех же данных.
  const pick = (state: { activeIndex?: number | string | null }) => {
    const index = Number(state?.activeIndex);
    const day = Number.isInteger(index) ? data[index]?.day : undefined;
    if (day) toggleFocusedDay(day);
  };

  return (
    <ChartContainer config={config} className="h-[280px] w-full [&_.recharts-surface]:cursor-pointer">
      <ComposedChart data={data} margin={{ left: 4, right: 4, top: 8, bottom: 8 }} onClick={pick}>
        <CartesianGrid vertical={false} yAxisId="reactions" stroke="var(--border)" />
        <Bar yAxisId="views" dataKey="postsBand" fill="var(--muted-foreground)"
          fillOpacity={0.2} radius={[3, 3, 0, 0]} maxBarSize={26} isAnimationActive animationDuration={420} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} height={28} tickMargin={8} />
        {/* Повёрнутых подписей у осей нет: вдвоём они съедали восемьдесят
            пикселей ширины, а какая шкала чья, говорит легенда над графиком
            цветом. */}
        <YAxis yAxisId="reactions" orientation="left" tickLine={false} axisLine={false}
          width={52} allowDecimals={false} tickFormatter={axisNumber} tickMargin={6} />
        <YAxis yAxisId="views" orientation="right" tickLine={false} axisLine={false}
          width={52} allowDecimals={false} tickFormatter={axisNumber} tickMargin={6} />
        <ChartTooltip cursor={{ strokeDasharray: "4 4" }} content={(props) => <TrendTooltip {...props} primary={primary} />} />
        <Line yAxisId="reactions" dataKey="medianReactions" type="monotone" stroke="var(--chart-1)"
          strokeWidth={2.5} dot={(props) => markedDot(props, focused, "var(--chart-1)")} activeDot={{ r: 5 }}
          connectNulls={false} isAnimationActive animationDuration={420} />
        <Line yAxisId="views" dataKey="medianViews" type="monotone" stroke="var(--chart-2)"
          strokeWidth={2.5} dot={(props) => markedDot(props, focused, "var(--chart-2)")} activeDot={{ r: 5 }}
          connectNulls={false} isAnimationActive animationDuration={420} />
      </ComposedChart>
    </ChartContainer>
  );
}

function TrendTooltip({ active, payload, primary }: { active?: boolean; payload?: unknown; primary: string }) {
  if (!active || !Array.isArray(payload) || !payload.length) return null;
  const point = (payload[0] as { payload?: Point & { label?: string } } | undefined)?.payload;
  if (!point) return null;
  return (
    <div className="border-border/50 bg-background grid min-w-[12rem] gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl">
      <div className="font-medium">{point.label}</div>
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className="size-2.5 shrink-0 rounded-[2px] bg-muted-foreground/40" />
        <span className="text-foreground tabular">Публикаций в день: {point.publishedCount}</span>
      </div>
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className="size-2.5 shrink-0 rounded-[2px]" style={{ background: "var(--chart-1)" }} />
        <span className="text-foreground tabular">Медиана {primary}: {legacyNumber(point.medianReactions)}</span>
      </div>
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className="size-2.5 shrink-0 rounded-[2px]" style={{ background: "var(--chart-2)" }} />
        <span className="text-foreground tabular">Медиана просмотров: {legacyNumber(point.medianViews)}</span>
      </div>
    </div>
  );
}

/** Кружок рисуется только у выбранного дня: остальные точки читаются по линии. */
function markedDot(props: unknown, focused: string | null, color: string) {
  const { cx, cy, payload, key } = props as { cx?: number; cy?: number; key?: string; payload?: { day?: string } };
  if (!focused || payload?.day !== focused || cx === undefined || cy === undefined) {
    return <g key={key} />;
  }
  return <circle key={key} cx={cx} cy={cy} r={5} fill={color} stroke="var(--background)" strokeWidth={2} />;
}
