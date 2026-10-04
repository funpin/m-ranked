import type { Finding } from "@/lib/types";
import { formatMetric } from "@/lib/format";

const WIDTH = 72;
const HEIGHT = 24;
const PAD = 2;

/** Как пост набирал взаимодействия на 1–24 ч против нормы аккаунта.
 *  Ось часов логарифмическая: первые часы различимы, сутки помещаются. */
export function GrowthSparkline({ curve }: { curve: Finding["curve"] }) {
  const values = [...curve.post, ...curve.norm].filter((value): value is number => value !== null);
  const known = curve.post.filter((value) => value !== null).length;
  if (known < 2) return <span className="text-muted-foreground text-xs">—</span>;
  const top = Math.max(...values, 1);
  const logs = curve.hours.map((hour) => Math.log(hour + 1));
  const x = (index: number) => PAD + ((logs[index] - logs[0]) / (logs.at(-1)! - logs[0])) * (WIDTH - PAD * 2);
  const y = (value: number) => HEIGHT - PAD - (value / top) * (HEIGHT - PAD * 2);
  const path = (series: readonly (number | null)[]) => series
    .map((value, index) => value === null ? null : `${x(index).toFixed(1)},${y(value).toFixed(1)}`)
    .filter(Boolean).join(" ");
  const label = curve.hours.map((hour, index) => {
    const post = curve.post[index];
    const norm = curve.norm[index];
    return post === null ? null : `${hour} ч: ${formatMetric(post)}${norm !== null ? ` при норме ${formatMetric(norm, true)}` : ""}`;
  }).filter(Boolean).join("; ");
  return (
    <svg width={WIDTH} height={HEIGHT} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`Набор взаимодействий — ${label}`}
      className="shrink-0 overflow-visible" data-testid="growth-sparkline">
      <title>{label}</title>
      {curve.norm.some((value) => value !== null)
        ? <polyline points={path(curve.norm)} fill="none" stroke="currentColor" strokeWidth={1.25} strokeDasharray="2 2" className="text-muted-foreground" />
        : null}
      <polyline points={path(curve.post)} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" className="text-primary" />
    </svg>
  );
}
