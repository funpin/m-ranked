/** Параметры прежнего обзора на главной странице. */
const OVERVIEW_PARAMS = ["platform", "period", "q", "sort", "direction", "cursor", "limit", "submitted"] as const;

/** Только старые ссылки на обзор с «/» ведут на /review.
 * /rating — вкладка «Рейтинг» (прогноз М-Рейтинга и наш рейтинг) и здесь не перехватывается. */
export function overviewRedirect(url: URL): URL | null {
  if (url.pathname === "/statistics" || url.pathname === "/statistics/") return renamed(url, "/findings");
  if (url.pathname !== "/" || !OVERVIEW_PARAMS.some((name) => url.searchParams.has(name))) return null;
  return renamed(url, "/review");
}

/** Раздел «Статистика» стал «Находками» (/findings): старые ссылки и закладки
 *  ведут туда же со всеми параметрами фильтров. */
function renamed(url: URL, pathname: string): URL {
  const target = new URL(url.href);
  target.pathname = pathname;
  return target;
}
