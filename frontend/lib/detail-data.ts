import { api } from "./api";
import { collectPages, uniqueRows } from "./continuation";
import type { LegacyAccountType, LegacyPublicationType, PublicationHistory } from "./types";

export async function loadAccountPublications(id: number, type: LegacyAccountType) {
  const pages = await collectPages((cursor) => api.accountPublications(id, type, cursor), (page) => page.nextCursor);
  return { ...pages[0]!, items: uniqueRows(pages.flatMap((page) => page.items), (post) => post.publicationId), nextCursor: null };
}
export type DetailHistory=PublicationHistory & {accountDisplayName?:string;previousDisplayId?:string;nextDisplayId?:string};
export async function loadPublicationHistory(id: number, type: LegacyPublicationType): Promise<DetailHistory> {
  const pages = await collectPages((cursor) => api.publicationHistory(id, type, cursor), (page) => page.nextCursor);
  const items = uniqueRows(pages.flatMap((page) => page.items), (row) => row.snapshotId).sort((a,b) => Date.parse(a.observedAt) - Date.parse(b.observedAt) || a.snapshotId.localeCompare(b.snapshotId, undefined, { numeric: true }));
  const first=pages[0]!;
  const publication=first.publication;
  const related=await Promise.all([
    publication.accountLegacyId && publication.accountLegacyType ? api.account(publication.accountLegacyId,publication.accountLegacyType) : null,
    first.previousLegacyId ? api.publication(first.previousLegacyId,type) : null,
    first.nextLegacyId ? api.publication(first.nextLegacyId,type) : null,
  ]);
  if(related.some((row)=>row && row.datasetRevision!==first.datasetRevision)) throw new Error("Publication revision changed while reading navigation");
  const [account,previous,next]=related;
  return { ...first, items, nextCursor: null, accountDisplayName:publication.platform === "telegram" ? publication.accountName ?? undefined : account?.institutionShortName || account?.institutionName, previousDisplayId:previous?.displayExternalId ?? previous?.externalId ?? undefined,nextDisplayId:next?.displayExternalId ?? next?.externalId ?? undefined };
}
