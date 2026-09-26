import { FULL_PUBLICATION_HISTORY_LIMIT } from "./types";

const DAY = 86_400;

/** Сколько готовая страница поста живёт в кэше nginx (X-Accel-Expires), по
 *  возрасту поста: у старше сорока суток сбор закончен и страница не меняется,
 *  у свежего замеры приходят каждые несколько минут. Отставание не больше шага
 *  сбора этого возраста. */
export function publicationCacheSeconds(publishedAt: string, now = Date.now()): number {
  const age = (now - Date.parse(publishedAt)) / 1000;
  if (!Number.isFinite(age) || age < 0) return 0;
  if (age >= 40 * DAY) return DAY;
  if (age >= 7 * DAY) return 3600;
  if (age >= DAY) return 900;
  return 120;
}

/** Срок кэша для /publications/{uuid} — только если история поста получена.
 *
 *  nginx кэширует по X-Accel-Expires ответ с любым статусом, а экран «не
 *  удалось загрузить данные» отдаётся с кодом 200: поставь срок вслепую — и
 *  сбой API висел бы в кэше сутки. Поэтому прокси сначала сам запрашивает ту
 *  же историю, что и страница (API кладёт ответ в свой кэш, и странице он
 *  достаётся почти бесплатно), и ставит срок, только если она пришла. */
export async function publicationCacheHeader(url: URL, apiOrigin: string,
  fetcher: typeof fetch = fetch): Promise<string | null> {
  const match = /^\/publications\/([0-9a-f-]{36})$/i.exec(url.pathname);
  if (!match) return null;
  try {
    const target = new URL(`/api/v1/publications/${match[1]}/history`, apiOrigin);
    target.searchParams.set("limit", String(FULL_PUBLICATION_HISTORY_LIMIT));
    const response = await fetcher(target, { cache: "no-store", signal: AbortSignal.timeout(10_000) });
    if (!response.ok) return null;
    const body = await response.json() as { publication?: { publishedAt?: string } };
    const seconds = body.publication?.publishedAt ? publicationCacheSeconds(body.publication.publishedAt) : 0;
    return seconds > 0 ? String(seconds) : null;
  } catch {
    return null;
  }
}
