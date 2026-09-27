import type {
  HistorySnapshot, PublicationAnomalyAnalysis, PublicationHistory, PublicationListItem,
} from "./types";

/** Local contextual method. Its values are descriptive, not calibrated p-values. */
const BOUNDARY_TOLERANCE_MS = 2 * 60 * 60 * 1000;
const NEARBY_POSTS = 4;
const MAX_EVENTS_PER_WINDOW = 6;

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
export type ContextTrace = { displayId: string; points: ContextPoint[]; publicationId?: string };

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
  omittedEventCount: number;
  positivePeerCount: number;
  medianPeerLogGrowth: number | null;
  relativeLogGrowth: number | null;
  matchedContrast: {
    targetExtraPerHour: number;
    peerExtraMedianPerHour: number;
    contrastPerHour: number;
    matchedPeerCount: number;
    rounded: boolean;
  } | null;
  context: "neighbor_and_shared" | "neighbor_only" | "shared_channel" | "unresolved" | "insufficient_data";
};

export type ContextAssessment = {
  status: "contrast_available" | "insufficient_data" | "other_evidence";
  contextualized: number;
  totalLateSpikes: number;
  positiveContrast: number;
  nonpositiveContrast: number;
  unevaluated: number;
};

/** Direction of a descriptive comparison with older posts. It is not a
 * verdict: feed position and spillover from a new post remain uncontrolled. */
export function lateGrowthContrast(window: ContextWindow): "positive" | "nonpositive" | "unevaluated" {
  const contrast = window.matchedContrast;
  if (!contrast) return "unevaluated";
  return contrast.contrastPerHour > 0 ? "positive" : "nonpositive";
}

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

type QuietMatch = { ratePerHour: number; rounded: boolean };
const HOUR_MS = 60 * 60_000;

/** A same-post, same-duration observed control before the signal. It is only
 * a descriptive baseline: change-only history omits unchanged successful
 * reads. Never turn an absent match into a zero-rate control. */
function matchedQuietWindow(
  history: PublicationHistory, measured: WindowMeasurement,
  signalStart: string, publications: PublicationListItem[],
): QuietMatch | null {
  const signal = Date.parse(signalStart);
  const duration = Date.parse(measured.afterAt) - Date.parse(measured.beforeAt);
  if (!Number.isFinite(signal) || duration <= 0) return null;
  const rows = history.items.filter(accepted)
    .sort((a, b) => Date.parse(a.observedAt) - Date.parse(b.observedAt));
  const publicationTimes = publications.map((post) => Date.parse(post.publishedAt)).filter(Number.isFinite);
  let best: { match: QuietMatch; distance: number } | null = null;
  for (let i = 0; i < rows.length - 1; i++) {
    const before = rows[i]!;
    const from = Date.parse(before.observedAt);
    if (from < signal - 24 * HOUR_MS || from > signal - duration - 2 * HOUR_MS) continue;
    const desired = from + duration;
    let lo = i + 1, hi = rows.length;
    while (lo < hi) {
      const mid = Math.floor((lo + hi) / 2);
      if (Date.parse(rows[mid]!.observedAt) < desired) lo = mid + 1;
      else hi = mid;
    }
    for (const index of [lo - 1, lo]) {
      if (index <= i || index >= rows.length) continue;
      const after = rows[index]!;
      const to = Date.parse(after.observedAt);
      const elapsed = to - from;
      if (elapsed < duration * 0.75 || elapsed > duration * 1.25 ||
          to > signal - 2 * HOUR_MS || after.views.value! < before.views.value! ||
          publicationTimes.some((at) => at >= from - 2 * HOUR_MS && at <= to + 2 * HOUR_MS)) continue;
      const distance = signal - to + Math.abs(elapsed - duration);
      if (best === null || distance < best.distance) best = {
        distance,
        match: {
          ratePerHour: (after.views.value! - before.views.value!) / (elapsed / HOUR_MS),
          rounded: before.views.quality === "rounded" || after.views.quality === "rounded",
        },
      };
    }
  }
  return best?.match ?? null;
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

/** A signal window is only resolved to polling precision. A publication just
 * before its rounded start remains a candidate, even if it is far in the feed. */
export function selectWindowEvents(
  publications: PublicationListItem[], targetId: string,
  startAt: string, endAt: string, scaleSeconds: number,
): { events: ContextEvent[]; omitted: number } {
  const ordered = [...publications].sort(comparePosts);
  const position = ordered.findIndex((post) => post.publicationId === targetId);
  if (position < 0) return { events: [], omitted: 0 };
  const start = Date.parse(startAt), end = Date.parse(endAt);
  const tolerance = Math.min(60 * 60_000, Math.max(15 * 60_000, (scaleSeconds || 0) * 1000));
  const candidates = ordered.flatMap((post, index) => {
    const at = Date.parse(post.publishedAt);
    if (index <= position || at < start - tolerance || at > end) return [];
    return [{ publicationId: post.publicationId, displayId: post.displayExternalId ?? post.publicationId,
      publishedAt: post.publishedAt, observedFeedDistance: index - position }];
  });
  return { events: candidates.slice(0, MAX_EVENTS_PER_WINDOW), omitted: Math.max(0, candidates.length - MAX_EVENTS_PER_WINDOW) };
}

export function evaluateNeighborContext(input: {
  analysis: PublicationAnomalyAnalysis;
  targetHistory: PublicationHistory;
  publications: PublicationListItem[];
  peerHistories: ReadonlyMap<string, PublicationHistory>;
}): ContextWindow[] {
  const { analysis, targetHistory, publications, peerHistories } = input;
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
      const selected = selectWindowEvents(publications, targetHistory.publication.publicationId,
        signal.startAt, signal.endAt, signal.scaleSeconds);
      const events = selected.events;
      const traceEnd = target?.afterAt ?? signal.endAt;
      const eventTraces = events.flatMap((event) => {
          const history = peerHistories.get(event.publicationId);
          return history ? [{ publicationId: event.publicationId, displayId: event.displayId,
            points: trace(history, event.publishedAt, traceEnd) }] : [];
        });
      const positivePeerCount = peers.filter((peer) => peer.measurement.displayedDelta > 0).length;
      const medianPeerLogGrowth = median(peers.map((peer) => peer.measurement.logGrowth));
      const quietTarget = target && matchedQuietWindow(targetHistory, target, signal.startAt, publications);
      const targetExtra = target && quietTarget
        ? target.displayedDelta / ((Date.parse(target.afterAt) - Date.parse(target.beforeAt)) / HOUR_MS) - quietTarget.ratePerHour
        : null;
      const peerExtra = peerMeasurements.flatMap(({ measurement, history }) => {
        const quiet = matchedQuietWindow(history, measurement, signal.startAt, publications);
        return quiet ? [{
          value: measurement.displayedDelta /
            ((Date.parse(measurement.afterAt) - Date.parse(measurement.beforeAt)) / HOUR_MS) - quiet.ratePerHour,
          rounded: measurement.rounded || quiet.rounded,
        }] : [];
      });
      const peerMedian = median(peerExtra.map((item) => item.value));
      const matchedContrast = events.length > 0 && targetExtra !== null && peerMedian !== null && peerExtra.length >= 2
        ? { targetExtraPerHour: targetExtra, peerExtraMedianPerHour: peerMedian,
            contrastPerHour: targetExtra - peerMedian, matchedPeerCount: peerExtra.length,
            rounded: !!(target?.rounded || quietTarget?.rounded || peerExtra.some((item) => item.rounded)) }
        : null;
      const near = events.some((event) => event.observedFeedDistance <= NEARBY_POSTS);
      const shared = positivePeerCount >= 2;
      const context = !target || peers.length < 2 ? "insufficient_data"
        : near && shared ? "neighbor_and_shared"
          : near ? "neighbor_only" : shared ? "shared_channel" : "unresolved";
      return {
        startAt: signal.startAt, endAt: signal.endAt, originalStrength: signal.strength,
        originalFormula: signal.formula, target, targetTrace, peers, peerTraces,
        events, eventTraces, omittedEventCount: selected.omitted, positivePeerCount,
        medianPeerLogGrowth,
        relativeLogGrowth: target && medianPeerLogGrowth !== null ? target.logGrowth - medianPeerLogGrowth : null,
        matchedContrast,
        context,
      };
    });
}

/** Descriptive local comparison. Neither sign confirms nor excludes a signal. */
export function assessNeighborContext(
  analysis: PublicationAnomalyAnalysis, windows: ContextWindow[], consistentRevision: boolean,
): ContextAssessment {
  const totalLateSpikes = analysis.signals.filter((signal) => signal.pattern === 2 && signal.metric === "views").length;
  const contextualized = windows.filter((window) =>
    window.context === "neighbor_and_shared" || window.context === "shared_channel").length;
  const evidence = consistentRevision && windows.length === totalLateSpikes
    ? windows.map(lateGrowthContrast) : [];
  const positiveContrast = evidence.filter((item) => item === "positive").length;
  const nonpositiveContrast = evidence.filter((item) => item === "nonpositive").length;
  const unevaluated = totalLateSpikes - positiveContrast - nonpositiveContrast;
  const status = !consistentRevision ? "insufficient_data"
    : analysis.signals.length !== totalLateSpikes && totalLateSpikes > 0 ? "other_evidence"
    : positiveContrast + nonpositiveContrast > 0 ? "contrast_available" : "insufficient_data";
  return { status, contextualized, totalLateSpikes, positiveContrast, nonpositiveContrast, unevaluated };
}
