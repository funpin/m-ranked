/** Canonical public identities are shared across all platforms. */
export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const accountHref = (id: string) => `/accounts/${id.toLowerCase()}`;
export const publicationHref = (id: string) => `/publications/${id.toLowerCase()}`;

export function withSearch(path: string, query: Record<string, string | string[] | undefined>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    for (const item of Array.isArray(value) ? value : value === undefined ? [] : [value]) params.append(key, item);
  }
  return params.size ? `${path}?${params}` : path;
}
