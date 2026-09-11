import { api } from "./api";
import type { LegacyAccountType, LegacyPublicationType, PublicationHistory } from "./types";

export async function loadAccountPublications(id: number | string, type?: LegacyAccountType, limit = 100) {
  return api.accountPublications(id, type, limit);
}
export type DetailHistory=PublicationHistory & {accountDisplayName?:string;previousDisplayId?:string;nextDisplayId?:string;accountId?:string;previousPublicationId?:string;nextPublicationId?:string};
export async function loadPublicationHistory(id: number | string, type?: LegacyPublicationType, limit = 100): Promise<DetailHistory> {
  const first=await api.publicationHistory(id, type, limit);
  const items = [...first.items].sort((a,b) => Date.parse(a.observedAt) - Date.parse(b.observedAt) || a.snapshotId.localeCompare(b.snapshotId, undefined, { numeric: true }));
  const publication=first.publication;
  const related=await Promise.all([
    publication.accountLegacyId && publication.accountLegacyType ? api.account(publication.accountLegacyId,publication.accountLegacyType) : null,
    first.previousLegacyId ? api.publication(first.previousLegacyId,publication.legacyType) : null,
    first.nextLegacyId ? api.publication(first.nextLegacyId,publication.legacyType) : null,
  ]);
  if(related.some((row)=>row && row.datasetRevision!==first.datasetRevision)) throw new Error("Publication revision changed while reading navigation");
  const [account,previous,next]=related;
  return { ...first, items, accountId:account?.accountId, previousPublicationId:previous?.publicationId, nextPublicationId:next?.publicationId, accountDisplayName:publication.platform === "telegram" ? publication.accountName ?? undefined : account?.institutionShortName || account?.institutionName, previousDisplayId:previous?.displayExternalId ?? previous?.externalId ?? undefined,nextDisplayId:next?.displayExternalId ?? next?.externalId ?? undefined };
}
