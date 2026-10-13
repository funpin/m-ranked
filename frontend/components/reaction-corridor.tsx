/** «Слишком ровный отклик»: реакции к 72 часам каждого поста по порядку
 *  публикации против пуассоновского коридора своего дня (среднее дня ±2√λ).
 *  Живые посты одного дня выходят за коридор — интерес к ним разный; у
 *  находки они идут внутри него, точнее, чем позволяет случайность. */

type Point = { day: string; reactions: number };

const W = 560, H = 190, L = 34, R = 8, T = 10, B = 26;

export function ReactionCorridor({ points, dayMinPosts }: { points: readonly Point[]; dayMinPosts: number }) {
  if (points.length < 2) return null;
  const byDay = new Map<string, number[]>();
  for (const point of points) byDay.set(point.day, [...(byDay.get(point.day) ?? []), point.reactions]);
  const band = points.map((point) => {
    const values = byDay.get(point.day)!;
    if (values.length < dayMinPosts) return null;
    const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
    return { mean, low: Math.max(0, mean - 2 * Math.sqrt(mean)), high: mean + 2 * Math.sqrt(mean) };
  });
  const top = niceMax(Math.max(...points.map((point) => point.reactions), ...band.map((item) => item?.high ?? 0)));
  const x = (index: number) => L + (index / (points.length - 1)) * (W - L - R);
  const y = (value: number) => T + (1 - value / top) * (H - T - B);
  const judged = points.filter((_, index) => band[index]);
  const outside = points.filter((point, index) => band[index] && (point.reactions < band[index]!.low || point.reactions > band[index]!.high)).length;
  // Коридор — ступеньками по дням: у каждого поста — коридор его дня.
  const runs: { from: number; to: number; low: number; high: number; mean: number }[] = [];
  band.forEach((item, index) => {
    const last = runs.at(-1);
    if (!item) return;
    if (last && last.to === index - 1 && points[index]!.day === points[last.to]!.day) last.to = index;
    else runs.push({ from: index, to: index, ...item });
  });
  const half = (W - L - R) / (points.length - 1) / 2;
  const line = points.map((point, index) => `${x(index).toFixed(1)},${y(point.reactions).toFixed(1)}`).join(" ");
  const ticks = [0, top / 2, top];
  const labels = [0, Math.floor((points.length - 1) / 2), points.length - 1];
  return <figure className="grid gap-2" data-testid="reaction-corridor">
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img"
      aria-label={`Реакции к 72 часам: ${outside} из ${judged.length} постов вне коридора случайности своего дня`}>
      {ticks.map((tick) => <g key={tick}>
        <line x1={L} x2={W - R} y1={y(tick)} y2={y(tick)} className="stroke-border" strokeWidth="1" />
        <text x={L - 6} y={y(tick) + 3} textAnchor="end" className="fill-muted-foreground text-[10px] tabular-nums">{Math.round(tick)}</text>
      </g>)}
      {runs.map((run) => {
        // Ступенька дня — до середины между соседними постами, в пределах области графика.
        const from = Math.max(L, x(run.from) - half), to = Math.min(W - R, x(run.to) + half);
        return <g key={`${run.from}-${run.to}`}>
          <rect x={from} width={Math.max(to - from, 1)} y={y(run.high)}
            height={Math.max(y(run.low) - y(run.high), 1)} className="fill-muted-foreground/15" />
          <line x1={from} x2={to} y1={y(run.mean)} y2={y(run.mean)}
            className="stroke-muted-foreground" strokeWidth="1" strokeDasharray="3 3" />
        </g>;
      })}
      <polyline points={line} fill="none" className="stroke-chart-3" strokeWidth="1.5" strokeLinejoin="round" />
      {points.map((point, index) => <circle key={index} cx={x(index)} cy={y(point.reactions)} r={points.length > 80 ? 1.6 : 2.4}
        className="fill-chart-3"><title>{`${point.day}: ${point.reactions} реакций`}</title></circle>)}
      {labels.map((index) => <text key={index} x={x(index)} y={H - 8}
        textAnchor={index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"}
        className="fill-muted-foreground text-[10px] tabular-nums">{shortDay(points[index]!.day)}</text>)}
    </svg>
    <figcaption className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
      <span className="inline-flex items-center gap-1.5"><span className="bg-chart-3 size-2 rounded-full" />реакции поста к 72 ч</span>
      <span className="inline-flex items-center gap-1.5"><span className="bg-muted-foreground/30 h-2 w-3 rounded-[2px]" />коридор случайности дня ±2√λ</span>
      <span className="inline-flex items-center gap-1.5"><span className="border-muted-foreground w-3 border-t border-dashed" />среднее дня</span>
      <span className="basis-full">
        Вне коридора — {outside} из {judged.length} постов{judged.length ? ` (${Math.round((outside / judged.length) * 100)} %)` : ""}. У живой
        аудитории посты одного дня часто выходят за него: интерес к ним разный.
      </span>
    </figcaption>
  </figure>;
}

function niceMax(value: number) {
  if (value <= 0) return 1;
  const exponent = 10 ** Math.floor(Math.log10(value));
  const fraction = value / exponent;
  const step = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((item) => fraction <= item) ?? 10;
  return step * exponent;
}

function shortDay(day: string) {
  const [, month, date] = day.split("-");
  return `${date}.${month}`;
}
