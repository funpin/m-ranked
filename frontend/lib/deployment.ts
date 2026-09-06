export function publicOrigin(value = process.env.SITE_ORIGIN ?? "https://m.funpin.org"): URL {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("SITE_ORIGIN must be an HTTPS origin without credentials, path, query or fragment");
  }
  return url;
}
