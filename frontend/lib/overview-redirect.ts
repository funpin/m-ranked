/** Параметры прежнего обзора на главной странице. */
const OVERVIEW_PARAMS = ["platform", "period", "q", "sort", "direction", "cursor", "limit", "submitted"] as const;

/** Только старые ссылки на обзор с «/» ведут на /review.
 * /rating оставлен отдельному будущему продукту и здесь не перехватывается. */
export function overviewRedirect(url: URL): URL | null {
  if (url.pathname !== "/" || !OVERVIEW_PARAMS.some((name) => url.searchParams.has(name))) return null;
  const target = new URL(url.href);
  target.pathname = "/review";
  return target;
}
