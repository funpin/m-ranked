import type {
  HistorySnapshot, PublicationAnomalyAnalysis, PublicationHistory, PublicationListItem,
} from "./types";

/** Local contextual method. Its values are descriptive, not calibrated p-values. */
const BOUNDARY_TOLERANCE_MS = 2 * 60 * 60 * 1000;
const NEARBY_POSTS = 4;

export type WindowMeasurement = {
  beforeAt: string;
  afterAt: string;
  beforeViews: number;
  afterViews: number;
  displayedDelta: number;
  logGrowth: number;
  rounded: boolean;
};

export type ContextEvent = {
  publicationId: string;
  displayId: string;
  publishedAt: string;
  observedFeedDistance: number;
};

export type ContextPoint = { observedAt: string; views: number };
export type ContextTrace = { displayId: string; points: ContextPoint[] };

export type ContextWindow = {
  startAt: string;
  endAt: string;
  originalStrength: number;
  originalFormula: string;
  target: WindowMeasurement | null;
  targetTrace: ContextPoint[];
  peers: { displayId: string; measurement: WindowMeasurement }[];
  peerTraces: ContextTrace[];
  events: ContextEvent[];
  eventTraces: ContextTrace[];
  positivePeerCount: number;
  medianPeerLogGrowth: number | null;
  conditionalLogResidual: number | null;
  context: "neighbor_and_shared" | "neighbor_only" | "shared_channel" | "unresolved" | "insufficient_data";
};

export type ContextAssessment = {
  status: "requires_review" | "insufficient_data" | "other_evidence";
  contextualized: number;
  totalLateSpikes: number;
};

function accepted(row: HistorySnapshot): row is HistorySnapshot {
  return !row.synthetic && !row.intervalUncertain
    && row.views.value !== null
    && (row.views.quality === "exact" || row.views.quality === "rounded");
}

/** Bracket the whole signal; sparse observations never become invented zeros. */
export function bracketViews(history: PublicationHistory, startAt: string, endAt: string): WindowMeasurement | null {
  const start = Date.parse(startAt), end = Date.parse(endAt);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) return null;
  const rows = [...history.items].filter(accepted)
    .sort((a, b) => Date.parse(a.observedAt) - Date.parse(b.observedAt));
  const before = [...rows].reverse().find((row) => Date.parse(row.observedAt) <= start);
  const after = rows.find((row) => Date.parse(row.observedAt) >= end);
  if (!before || !after || start - Date.parse(before.observedAt) > BOUNDARY_TOLERANCE_MS
      || Date.parse(after.observedAt) - end > BOUNDARY_TOLERANCE_MS) return null;
  const beforeViews = before.views.value!, afterViews = after.views.value!;
  if (afterViews < beforeViews) return null; // correction/reset: not a growth observation
  return {
    beforeAt: before.observedAt, afterAt: after.observedAt, beforeViews, afterViews,
    displayedDelta: afterViews - beforeViews,
    logGrowth: Math.log1p(afterViews) - Math.log1p(beforeViews),
    rounded: before.views.quality === "rounded" || after.views.quality === "rounded",
  };
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const ordered = [...values].sort((a, b) => a - b);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[middle]! : (ordered[middle - 1]! + ordered[middle]!) / 2;
}

/** Keep the real observation times; never synthesize points between polls. */
function trace(history: PublicationHistory, from: string, to: string): ContextPoint[] {
  const low = Date.parse(from), high = Date.parse(to);
  const points = history.items.filter(accepted)
    .filter((row) => {
      const at = Date.parse(row.observedAt);
      return at >= low && at <= high;
    })
    .sort((a, b) => Date.parse(a.observedAt) - Date.parse(b.observedAt))
    .map((row) => ({ observedAt: row.observedAt, views: row.views.value! }));
  if (points.length <= 24) return points;
  return Array.from({ length: 24 }, (_, index) => points[Math.round(index * (points.length - 1) / 23)]!);
}

function comparePosts(a: PublicationListItem, b: PublicationListItem): number {
  const date = Date.parse(a.publishedAt) - Date.parse(b.publishedAt);
  if (date) return date;
  const left = Number(a.displayExternalId), right = Number(b.displayExternalId);
  if (Number.isSafeInteger(left) && Number.isSafeInteger(right) && left !== right) return left - right;
  return a.publicationId.localeCompare(b.publicationId);
}

/** Small same-channel peer set, chosen before looking at any signal values. */
export function selectContextPeers(publications: PublicationListItem[], targetId: string): PublicationListItem[] {
  const ordered = [...publications].sort(comparePosts);
  const position = ordered.findIndex((post) => post.publicationId === targetId);
  if (position < 0) return [];
  return ordered.slice(Math.max(0, position - 2), position)
    .concat(ordered.slice(position + 1, position + 5));
}

export function evaluateNeighborContext(input: {
  analysis: PublicationAnomalyAnalysis;
  targetHistory: PublicationHistory;
  publications: PublicationListItem[];
  peerHistories: ReadonlyMap<string, PublicationHistory>;
}): ContextWindow[] {
  const { analysis, targetHistory, publications, peerHistories } = input;
  const ordered = [...publications].sort(comparePosts);
  const position = ordered.findIndex((post) => post.publicationId === targetHistory.publication.publicationId);
  const peerPosts = selectContextPeers(publications, targetHistory.publication.publicationId);
  return analysis.signals.filter((signal) => signal.pattern === 2 && signal.metric === "views")
    .map((signal) => {
      const target = bracketViews(targetHistory, signal.startAt, signal.endAt);
      const targetTrace = target ? trace(targetHistory, target.beforeAt, target.afterAt) : [];
      const peerMeasurements = peerPosts.flatMap((post) => {
        if (Date.parse(post.publishedAt) >= Date.parse(signal.startAt)) return [];
        const history = peerHistories.get(post.publicationId);
        const measurement = history && bracketViews(history, signal.startAt, signal.endAt);
        return measurement ? [{ displayId: post.displayExternalId ?? post.publicationId, measurement, history }] : [];
      });
      const peers = peerMeasurements.map(({ displayId, measurement }) => ({ displayId, measurement }));
      const peerTraces = peerMeasurements.map((peer) => ({
        displayId: peer.displayId,
        points: trace(peer.history, peer.measurement.beforeAt, peer.measurement.afterAt),
      }));
      const events = position < 0 ? [] : ordered.flatMap((post, index) => {
        const at = Date.parse(post.publishedAt);
        if (index <= position || at <= Date.parse(signal.startAt) || at > Date.parse(signal.endAt)) return [];
        return [{ publicationId: post.publicationId, displayId: post.displayExternalId ?? post.publicationId,
          publishedAt: post.publishedAt, observedFeedDistance: index - position }];
      });
      const traceEnd = target?.afterAt ?? signal.endAt;
      const eventTraces = events.filter((event) => event.observedFeedDistance <= NEARBY_POSTS)
        .flatMap((event) => {
          const history = peerHistories.get(event.publicationId);
          return history ? [{ displayId: event.displayId,
            points: trace(history, event.publishedAt, traceEnd) }] : [];
        });
      const positivePeerCount = peers.filter((peer) => peer.measurement.displayedDelta > 0).length;
      const medianPeerLogGrowth = median(peers.map((peer) => peer.measurement.logGrowth));
      const near = events.some((event) => event.observedFeedDistance <= NEARBY_POSTS);
      const shared = positivePeerCount >= 2;
      const context = !target || peers.length < 2 ? "insufficient_data"
        : near && shared ? "neighbor_and_shared"
          : near ? "neighbor_only" : shared ? "shared_channel" : "unresolved";
      return {
        startAt: signal.startAt, endAt: signal.endAt, originalStrength: signal.strength,
        originalFormula: signal.formula, target, targetTrace, peers, peerTraces,
        events, eventTraces, positivePeerCount,
        medianPeerLogGrowth,
        conditionalLogResidual: target && medianPeerLogGrowth !== null ? target.logGrowth - medianPeerLogGrowth : null,
        context,
      };
    });
}

/** Conservative status gate: common channel motion prevents a strong conclusion
 * from raw late-spike signals alone. It never asserts that a post is normal. */
export function assessNeighborContext(
  analysis: PublicationAnomalyAnalysis, windows: ContextWindow[], consistentRevision: boolean,
): ContextAssessment {
  const totalLateSpikes = analysis.signals.filter((signal) => signal.pattern === 2 && signal.metric === "views").length;
  const contextualized = windows.filter((window) =>
    window.context === "neighbor_and_shared" || window.context === "shared_channel").length;
  const sufficient = consistentRevision && totalLateSpikes > 0 && windows.length === totalLateSpikes
    && windows.every((window) => window.context !== "insufficient_data");
  const status = !sufficient ? "insufficient_data"
    : analysis.signals.length === totalLateSpikes && contextualized === totalLateSpikes
      ? "requires_review" : "other_evidence";
  return { status, contextualized, totalLateSpikes };
}
