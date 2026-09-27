import { api } from "./api";
import { assessNeighborContext, evaluateNeighborContext, selectContextPeers, selectWindowEvents } from "./neighbor-context";
import type { PublicationAnomalyAnalysis, PublicationHistory } from "./types";

/** Bounded read-only method on the real histories behind the ordinary post page. */
export async function loadNeighborContext(targetHistory: PublicationHistory, analysis: PublicationAnomalyAnalysis) {
  if (!["telegram", "max"].includes(targetHistory.publication.platform) ||
      !analysis.signals.some((signal) => signal.pattern === 2 && signal.metric === "views")) return null;
  const account = targetHistory.publication;
  if (!account.accountLegacyId || !account.accountLegacyType) {
    return { windows: [], assessment: assessNeighborContext(analysis, [], false),
      revisionMatched: false, peersRequested: 0, peersLoaded: 0 };
  }
  const publications = await api.accountPublications(
    account.accountLegacyId, account.accountLegacyType, 200, undefined, targetHistory.datasetRevision,
  );
  const peers = selectContextPeers(publications.items, account.publicationId);
  const eventIds = new Set(analysis.signals.filter((signal) => signal.pattern === 2 && signal.metric === "views")
    .flatMap((signal) => selectWindowEvents(publications.items, account.publicationId,
      signal.startAt, signal.endAt, signal.scaleSeconds).events.map((event) => event.publicationId)));
  const peerIds = new Set(peers.map((post) => post.publicationId));
  // Keep page load bounded while resolving later posts beyond the closest
  // feed neighbors. Missing event histories stay visibly unmeasured in the UI.
  const extraEvents = publications.items.filter((post) => eventIds.has(post.publicationId) && !peerIds.has(post.publicationId))
    .slice(0, 8);
  const requested = [...peers, ...extraEvents];
  const peerHistories = new Map<string, PublicationHistory>();
  // At most twelve histories and two concurrent requests bound API load.
  for (let offset = 0; offset < requested.length; offset += 2) {
    const batch = requested.slice(offset, offset + 2);
    const results = await Promise.allSettled(batch.map((post) => api.publicationHistory(post.publicationId, undefined, 500)));
    results.forEach((result, index) => {
      const post = batch[index]!;
      if (result.status === "fulfilled") peerHistories.set(post.publicationId, result.value);
    });
  }
  const windows = evaluateNeighborContext({ analysis, targetHistory, publications: publications.items, peerHistories });
  const revisions = new Set([targetHistory.datasetRevision, publications.datasetRevision,
    ...[...peerHistories.values()].map((history) => history.datasetRevision)]);
  const asOf = [targetHistory.asOf, publications.asOf,
    ...[...peerHistories.values()].map((history) => history.asOf)].map(Date.parse);
  // Cache age differs across endpoints. The API has no pinned history revision;
  // a ten-minute spread between read timestamps is therefore unrelated to
  // whether old, already observed samples can be compared. Only allow a
  // provisional diagnostic once every signal window predates the oldest read
  // by at least a day. Historical backfills can still change these samples.
  const matureWindows = asOf.every(Number.isFinite) && windows.every((window) =>
    Number.isFinite(Date.parse(window.endAt))
      && Date.parse(window.endAt) < Math.min(...asOf) - 24 * 60 * 60_000);
  const comparableReads = revisions.size === 1 || matureWindows;
  return { windows, assessment: assessNeighborContext(analysis, windows, comparableReads),
    revisionMatched: revisions.size === 1,
    peersRequested: requested.length, peersLoaded: peerHistories.size };
}

export type NeighborContextLoad = NonNullable<Awaited<ReturnType<typeof loadNeighborContext>>>;
