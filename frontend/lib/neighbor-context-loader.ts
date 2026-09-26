import { api } from "./api";
import { assessNeighborContext, evaluateNeighborContext, selectContextPeers } from "./neighbor-context";
import type { PublicationAnomalyAnalysis, PublicationHistory } from "./types";

/** Bounded read-only method on the real histories behind the ordinary post page. */
export async function loadNeighborContext(targetHistory: PublicationHistory, analysis: PublicationAnomalyAnalysis) {
  if (targetHistory.publication.platform !== "telegram" ||
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
  const peerHistories = new Map<string, PublicationHistory>();
  // A maximum of six peer histories and two concurrent requests bounds API load.
  for (let offset = 0; offset < peers.length; offset += 2) {
    const batch = peers.slice(offset, offset + 2);
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
  const closeReads = asOf.every(Number.isFinite) && Math.max(...asOf) - Math.min(...asOf) <= 10 * 60_000;
  const matureWindows = windows.every((window) => Date.parse(window.endAt) < Math.min(...asOf) - 24 * 60 * 60_000);
  // The live API changes revision every few seconds and does not expose a
  // revision selector for histories. Mature windows read within 10 minutes are
  // comparable for a provisional diagnostic, but remain non-atomic.
  const comparableReads = revisions.size === 1 || (closeReads && matureWindows);
  return { windows, assessment: assessNeighborContext(analysis, windows, comparableReads),
    revisionMatched: revisions.size === 1,
    peersRequested: peers.length, peersLoaded: peerHistories.size };
}

export type NeighborContextLoad = NonNullable<Awaited<ReturnType<typeof loadNeighborContext>>>;
