/** Параметры прежнего обзора: с ними «/» — это старая ссылка на рейтинг. */
const OVERVIEW_PARAMS = ["platform", "period", "q", "sort", "direction", "cursor", "limit", "submitted"] as const;

/** Обзор переехал на /rating, «/» стал главной страницей. Закладки и ссылки
 *  из соцсетей вида /?platform=vk&period=7d получают постоянное
 *  перенаправление с теми же параметрами; чистый «/» остаётся главной. */
export function overviewRedirect(url: URL): URL | null {
  if (url.pathname !== "/" || !OVERVIEW_PARAMS.some((name) => url.searchParams.has(name))) return null;
  const target = new URL(url.href);
  target.pathname = "/rating";
  return target;
}
