import type { ContextPoint, ContextWindow } from "@/lib/neighbor-context";

const WIDTH = 720;
const LEFT = 48;
const RIGHT = 12;
const eventTime = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" });

function timeLabel(value: number): string {
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" }).format(value);
}

/** Two aligned scales: new posts in views above, older posts in growth below. */
export function NeighborContextTimeline({ window }: { window: ContextWindow }) {
  const near = window.events.filter((event) => event.observedFeedDistance <= 4);
  const hasNew = near.length > 0;
  const firstNew = near.length ? Math.min(...near.map((event) => Date.parse(event.publishedAt))) : null;
  const firstNewAt = firstNew !== null ? new Date(firstNew).toISOString() : null;
  const start = Math.min(Date.parse(window.startAt),
    ...[window.target, ...window.peers.map((peer) => peer.measurement)].filter((value) => value !== null)
      .map((value) => Date.parse(value.beforeAt)));
  const end = Math.max(Date.parse(window.endAt),
    ...[window.target, ...window.peers.map((peer) => peer.measurement)].filter((value) => value !== null)
      .map((value) => Date.parse(value.afterAt)));
  const duration = Math.max(1, end - start);
  const x = (at: string) => LEFT + (Date.parse(at) - start) / duration * (WIDTH - LEFT - RIGHT);
  const oldTop = hasNew ? 83 : 23;
  const oldBottom = hasNew ? 137 : 91;
  const height = hasNew ? 180 : 115;
  const relative = (views: number, before: number) => Math.max(0, (views + 1) / (before + 1) * 100 - 100);
  const oldSeries = [
    ...(window.target ? [{ id: "post", before: window.target.beforeViews, points: window.targetTrace, target: true }] : []),
    ...window.peers.map((peer) => ({ id: peer.displayId, before: peer.measurement.beforeViews,
      points: window.peerTraces.find((trace) => trace.displayId === peer.displayId)?.points ?? [], target: false })),
  ];
  const oldMax = Math.max(1, ...oldSeries.flatMap((series) => series.points.map((point) => relative(point.views, series.before))));
  const newMax = Math.max(1, ...window.eventTraces.flatMap((series) => series.points.map((point) => point.views)));
  const oldY = (value: number) => oldBottom - value / oldMax * (oldBottom - oldTop);
  const newY = (value: number) => 64 - value / newMax * 34;
  const points = (rows: ContextPoint[], scale: (value: number) => number) =>
    rows.map((point) => `${x(point.observedAt).toFixed(1)},${scale(point.views).toFixed(1)}`).join(" ");
  const aria = `Общая временная ось ${timeLabel(start)} — ${timeLabel(end)}. ${near.length
    ? `Новые посты: ${near.map((event) => event.displayId).join(", ")}.` : "Новых постов рядом нет."} Синий — этот пост; зелёный — прежние посты канала. Точки — сохранённые замеры.`;

  return <div className="overflow-x-auto" data-testid="neighbor-context-timeline">
    <svg viewBox={`0 0 ${WIDTH} ${height}`} className="min-w-[34rem] w-full" role="img" aria-label={aria}>
      <title>{aria}</title>
      <rect x={x(window.startAt)} y="19" width={Math.max(1, x(window.endAt) - x(window.startAt))}
        height={oldBottom - 19} className="fill-blue-500/5 stroke-blue-500/20" strokeWidth="1" />
      {firstNewAt ? <rect x={x(firstNewAt)} y="19"
        width={Math.max(0, x(window.endAt) - x(firstNewAt))} height={oldBottom - 19}
        className="fill-amber-400/5" data-testid="after-neighbor-publication" /> : null}
      {hasNew ? <>
        <text x="0" y="17" className="fill-muted-foreground text-[11px]">Новые · просмотры</text>
        <text x={WIDTH - RIGHT} y="17" textAnchor="end" className="fill-muted-foreground text-[10px]">до {Math.round(newMax).toLocaleString("ru-RU")}</text>
        <line x1={LEFT} x2={WIDTH - RIGHT} y1="64" y2="64" className="stroke-border" />
        {near.map((event) => <g key={event.publicationId}>
          <line x1={x(event.publishedAt)} x2={x(event.publishedAt)} y1="25" y2={oldBottom}
            className="stroke-amber-400/70" strokeWidth="1.5" strokeDasharray="3 3" />
          <circle cx={x(event.publishedAt)} cy="25" r="3" className="fill-amber-400" />
          <text x={x(event.publishedAt)} y="156" textAnchor={x(event.publishedAt) > WIDTH - 64 ? "end" : x(event.publishedAt) < LEFT + 64 ? "start" : "middle"}
            className="fill-amber-400 text-[10px] font-semibold">№{event.displayId} · {eventTime.format(new Date(event.publishedAt))}</text>
        </g>)}
        {window.eventTraces.map((series) => <g key={series.displayId} className="text-amber-400">
          {series.points.length > 1 ? <polyline points={points(series.points, newY)} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /> : null}
          {series.points.map((point) => <circle key={point.observedAt} cx={x(point.observedAt)} cy={newY(point.views)} r="2" fill="currentColor" />)}
        </g>)}
      </> : null}
      <text x="0" y={oldTop - 5} className="fill-muted-foreground text-[11px]">Старые · прирост</text>
      <text x={WIDTH - RIGHT} y={oldTop - 5} textAnchor="end" className="fill-muted-foreground text-[10px]">до +{oldMax.toFixed(1)}%</text>
      {[0, 0.5, 1].map((fraction) => <line key={fraction} x1={LEFT} x2={WIDTH - RIGHT}
        y1={oldY(oldMax * fraction)} y2={oldY(oldMax * fraction)} className="stroke-border/70" strokeDasharray={fraction ? "2 4" : undefined} />)}
      {oldSeries.filter((series) => !series.target).map((series) => <g key={series.id} className="text-emerald-500">
        {series.points.length > 1 ? <polyline points={points(series.points, (value) => oldY(relative(value, series.before)))} fill="none"
          stroke="currentColor" strokeOpacity="0.65" strokeWidth="1.5" strokeLinejoin="round" /> : null}
        {series.points.map((point) => <circle key={point.observedAt} cx={x(point.observedAt)} cy={oldY(relative(point.views, series.before))} r="1.8" fill="currentColor" />)}
      </g>)}
      {oldSeries.filter((series) => series.target).map((series) => <g key={series.id} className="text-blue-500">
        {series.points.length > 1 ? <polyline points={points(series.points, (value) => oldY(relative(value, series.before)))} fill="none"
          stroke="currentColor" strokeWidth="3" strokeLinejoin="round" /> : null}
        {series.points.map((point) => <circle key={point.observedAt} cx={x(point.observedAt)} cy={oldY(relative(point.views, series.before))} r="2.2" fill="currentColor" />)}
      </g>)}
      <text x={LEFT} y={height - 3} className="fill-muted-foreground text-[10px]">{timeLabel(start)}</text>
      <text x={WIDTH - RIGHT} y={height - 3} textAnchor="end" className="fill-muted-foreground text-[10px]">{timeLabel(end)}</text>
    </svg>
  </div>;
}
