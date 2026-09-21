import { api, ApiError } from "./api";

/** Экран «Не удалось загрузить данные» отдаётся с кодом 200, поэтому в логах
 *  сервера от него не остаётся ничего. Причина пишется явно: без неё отказ,
 *  который видит пользователь, невозможно отличить от таймаута, разрыва
 *  соединения и ошибки самого API. */
export function reportDetailFailure(where: string, error: unknown) {
  const detail = error instanceof ApiError
    ? `ApiError ${error.status}`
    : error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  console.error(`detail page failed where=${where} reason=${detail}`);
}
import type { LegacyAccountType, LegacyPublicationType, PublicationHistory } from "./types";

export async function loadAccountPublications(id: number | string, type?: LegacyAccountType, limit = 100, revision?: number, day?: string) {
  return api.accountPublications(id, type, limit, undefined, revision, day);
}
export type DetailHistory=PublicationHistory & {accountDisplayName?:string;accountArchiveUrl?:string;previousDisplayId?:string;nextDisplayId?:string;accountId?:string;previousPublicationId?:string;nextPublicationId?:string};
export async function loadPublicationHistory(id: number | string, type?: LegacyPublicationType, limit = 100): Promise<DetailHistory> {
  const first=await api.publicationHistory(id, type, limit);
  const items = [...first.items].sort((a,b) => Date.parse(a.observedAt) - Date.parse(b.observedAt) || a.snapshotId.localeCompare(b.snapshotId, undefined, { numeric: true }));
  const publication=first.publication;
  // Остальные три запроса читают тот же снимок, что и история. Ревизия набора
  // данных на проде меняется каждые две секунды, и без закрепления примерно
  // каждый тринадцатый просмотр складывал страницу из двух снимков — а
  // несовпадение приводило к экрану «Сервис временно недоступен».
  const revision=first.datasetRevision;
  const related=await Promise.all([
    publication.accountLegacyId && publication.accountLegacyType ? api.account(publication.accountLegacyId,publication.accountLegacyType,revision) : null,
    first.previousLegacyId ? api.publication(first.previousLegacyId,publication.legacyType,revision) : null,
    first.nextLegacyId ? api.publication(first.nextLegacyId,publication.legacyType,revision) : null,
  ]);
  // Закреплённая ревизия могла быть вычищена обслуживанием — тогда сервер
  // отвечает по текущей. Это не повод показывать ошибку: подписи соседних
  // постов от расхождения в пару секунд не меняются, а ссылки остаются
  // верными, поэтому страница просто рисуется дальше.
  if(related.some((row)=>row && row.datasetRevision!==revision)) {
    console.warn("Соседние публикации пришли по другой ревизии набора данных");
  }
  const [account,previous,next]=related;
  return { ...first, items, accountId:account?.accountId, accountArchiveUrl:account?.archiveUrl ?? undefined, previousPublicationId:previous?.publicationId, nextPublicationId:next?.publicationId, accountDisplayName:publication.platform === "telegram" ? publication.accountName ?? undefined : account?.institutionShortName || account?.institutionName, previousDisplayId:previous?.displayExternalId ?? previous?.externalId ?? undefined,nextDisplayId:next?.displayExternalId ?? next?.externalId ?? undefined };
}
