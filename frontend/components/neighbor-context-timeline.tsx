import type { ContextEvent, ContextPoint, ContextWindow } from "@/lib/neighbor-context";

const W = 720, L = 42, R = 12, T = 18, B = 146, H = 181;
type GrowthPoint = { observedAt: string; growth: number };

function label(value: number): string {
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" }).format(value);
}

function growth(points: ContextPoint[], before: number): GrowthPoint[] {
  return points.map((point) => ({ observedAt: point.observedAt, growth: point.views - before }));
}

function valueOnLine(points: GrowthPoint[], at: number): number | null {
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]!, b = points[i]!;
    const left = Date.parse(a.observedAt), right = Date.parse(b.observedAt);
    if (left <= at && at <= right && right > left)
      return a.growth + (b.growth - a.growth) * (at - left) / (right - left);
  }
  return null;
}

/** A visual anchor sits on the blue line. The segment to the first actual
 * yellow read is dashed because its intermediate path was not observed. */
export function alignedEventGrowth(window: ContextWindow, event: ContextEvent): {
  anchor: GrowthPoint; observations: GrowthPoint[];
} | null {
  if (!window.target || window.targetTrace.length < 2) return null;
  const blue = growth(window.targetTrace, window.target.beforeViews);
  const at = Math.max(Date.parse(event.publishedAt), Date.parse(blue[0]!.observedAt));
  const anchor = valueOnLine(blue, at);
  const trace = window.eventTraces.find((item) => item.publicationId === event.publicationId)?.points ?? [];
  if (anchor === null || !trace.length) return null;
  return { anchor: { observedAt: new Date(at).toISOString(), growth: anchor },
    observations: trace.filter((point) => Date.parse(point.observedAt) >= at)
      .map((point) => ({ observedAt: point.observedAt, growth: anchor + point.views })) };
}

/** All colours share a single axis of additional displayed views. */
export function NeighborContextTimeline({ window, event }: { window: ContextWindow; event?: ContextEvent }) {
  const blue = window.target ? growth(window.targetTrace, window.target.beforeViews) : [];
  const green = window.peers.map((peer) => ({ id: peer.displayId,
    points: growth(window.peerTraces.find((trace) => trace.displayId === peer.displayId)?.points ?? [],
      peer.measurement.beforeViews) }));
  const yellow = event ? alignedEventGrowth(window, event) : null;
  const all = [...blue, ...green.flatMap((item) => item.points), ...(yellow ? [yellow.anchor, ...yellow.observations] : [])];
  const start = Math.min(Date.parse(window.startAt), ...all.map((point) => Date.parse(point.observedAt)),
    ...(event ? [Date.parse(event.publishedAt)] : []));
  const end = Math.max(Date.parse(window.endAt), ...all.map((point) => Date.parse(point.observedAt)));
  const low = Math.min(0, ...all.map((point) => point.growth));
  const high = Math.max(1, ...all.map((point) => point.growth));
  const span = Math.max(1, high - low);
  const x = (at: string) => L + (Date.parse(at) - start) / Math.max(1, end - start) * (W - L - R);
  const y = (count: number) => B - (count - low) / span * (B - T);
  const path = (rows: GrowthPoint[]) => rows.map((point) => `${x(point.observedAt).toFixed(1)},${y(point.growth).toFixed(1)}`).join(" ");
  const aria = `Прирост просмотров на одной шкале, ${label(start)} — ${label(end)}. Синий — этот пост, зелёные — старые посты${event ? `, жёлтый — пост №${event.displayId}. Жёлтая точка на синей линии — визуальный якорь, не замер.` : "; нового поста в окне нет."}`;
  return <div className="overflow-x-auto" data-testid="neighbor-context-timeline">
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[32rem]" role="img" aria-label={aria}>
      <title>{aria}</title>
      <rect x={x(window.startAt)} y={T} width={Math.max(1, x(window.endAt) - x(window.startAt))}
        height={B - T} className="fill-blue-500/5 stroke-blue-500/20" strokeWidth="1" />
      {[0, 0.5, 1].map((part) => <g key={part}>
        <line x1={L} x2={W - R} y1={y(low + span * part)} y2={y(low + span * part)}
          className="stroke-border/70" strokeDasharray={part ? "2 4" : undefined} />
        <text x={L - 6} y={y(low + span * part) + 3} textAnchor="end" className="fill-muted-foreground text-[9px]">
          {Math.round(low + span * part).toLocaleString("ru-RU")}</text>
      </g>)}
      {green.map((item) => <g key={item.id} className="text-emerald-500">
        {item.points.length > 1 ? <polyline points={path(item.points)} fill="none" stroke="currentColor" strokeOpacity="0.65" strokeWidth="1.5" /> : null}
        {item.points.map((point) => <circle key={point.observedAt} cx={x(point.observedAt)} cy={y(point.growth)} r="1.8" fill="currentColor" />)}
      </g>)}
      <g className="text-blue-500">
        {blue.length > 1 ? <polyline points={path(blue)} fill="none" stroke="currentColor" strokeWidth="3" /> : null}
        {blue.map((point) => <circle key={point.observedAt} cx={x(point.observedAt)} cy={y(point.growth)} r="2.1" fill="currentColor" />)}
      </g>
      {yellow && event ? <g className="text-amber-400" data-testid="new-post-growth">
        <line x1={x(yellow.anchor.observedAt)} x2={x(yellow.anchor.observedAt)} y1={T} y2={B}
          stroke="currentColor" strokeOpacity="0.5" strokeDasharray="3 4" />
        {yellow.observations.length ? <line x1={x(yellow.anchor.observedAt)} y1={y(yellow.anchor.growth)}
          x2={x(yellow.observations[0]!.observedAt)} y2={y(yellow.observations[0]!.growth)}
          stroke="currentColor" strokeWidth="2" strokeDasharray="3 3" /> : null}
        {yellow.observations.length > 1 ? <polyline points={path(yellow.observations)} fill="none" stroke="currentColor" strokeWidth="2.5" /> : null}
        <circle cx={x(yellow.anchor.observedAt)} cy={y(yellow.anchor.growth)} r="4"
          fill="var(--background)" stroke="currentColor" strokeWidth="2" data-testid="new-post-anchor" />
        {yellow.observations.map((point) => <circle key={point.observedAt} cx={x(point.observedAt)} cy={y(point.growth)} r="2" fill="currentColor" />)}
      </g> : null}
      <text x={L} y={H - 5} className="fill-muted-foreground text-[10px]">{label(start)}</text>
      <text x={W - R} y={H - 5} textAnchor="end" className="fill-muted-foreground text-[10px]">{label(end)}</text>
    </svg>
  </div>;
}
