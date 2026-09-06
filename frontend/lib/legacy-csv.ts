/** A streaming transport only. CSV layout and all data belong to the versioned API. */
export async function legacyCsv(request: Request, kind: "snapshots" | "posts", transport: typeof fetch = fetch) {
  const base = process.env.API_BASE_URL ?? "http://127.0.0.1:8080";
  const target = new URL(`/api/v1/legacy-exports/${kind}.csv`, base);
  target.search = new URL(request.url).search;
  try {
    const upstream = await transport(target, {
      cache: "no-store",
      redirect: "error",
      headers: { Accept: "text/csv, application/problem+json" },
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(310_000)]),
    });
    const headers = new Headers({ "Cache-Control": "no-store" });
    for (const key of ["Content-Type", "Content-Disposition", "Content-Length", "X-Dataset-Revision", "Retry-After"]) {
      const value = upstream.headers.get(key);
      if (value !== null) headers.set(key, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch {
    return Response.json({ type: "about:blank", title: "Export service unavailable", status: 502 }, {
      status: 502, headers: { "Cache-Control": "no-store" },
    });
  }
}
