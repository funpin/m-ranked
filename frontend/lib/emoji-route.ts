// Картинка custom emoji по номеру не меняется: кэш на месяц, без перепроверок.
const CACHE_CONTROL = "public, max-age=2592000, immutable";
const NOT_FOUND_DETAIL = "Реакция не найдена";
// Временный отказ API (Telegram недоступен) помнится не дольше часа.
const NOT_FOUND_MAX_AGE_SECONDS = 3600;
const ALLOWED_MEDIA_TYPES = new Set([
  "image/webp",
  "image/png",
  "image/gif",
  "image/jpeg",
]);

type Fetcher = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export interface EmojiRouteOptions {
  baseUrl?: string;
  fetcher?: Fetcher;
  timeoutMs?: number;
}

export function createEmojiRoute(options: EmojiRouteOptions = {}) {
  const baseUrl = normalizedBaseUrl(
    options.baseUrl ?? (process.env.PUBLIC_API_BASE_URL?.trim() || process.env.API_BASE_URL || "http://127.0.0.1:8080"),
  );
  const fetcher = options.fetcher ?? ((input, init) => fetch(input, init));
  const timeoutMs = options.timeoutMs ?? 21_000;

  return async function customEmoji(emojiId: string): Promise<Response> {
    if (!/^[0-9]{1,32}$/.test(emojiId)) return legacyNotFound();

    const url = new URL(`/api/v1/emoji/${emojiId}`, baseUrl);
    let upstream: Response;
    try {
      upstream = await fetcher(url, {
        method: "GET",
        headers: { Accept: "image/webp,image/png,image/gif,image/jpeg,*/*" },
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch {
      return internalError();
    }

    if (upstream.status === 404) return legacyNotFound(notFoundCacheControl(upstream.headers.get("cache-control")));
    if (upstream.status !== 200 || upstream.body === null) return internalError();

    const contentType = normalizedMediaType(upstream.headers.get("content-type"));
    const headers = new Headers({
      "Cache-Control": CACHE_CONTROL,
      "Content-Type": contentType,
    });
    const contentLength = upstream.headers.get("content-length");
    if (contentLength !== null && /^[0-9]+$/.test(contentLength)) {
      const byteLength = Number(contentLength);
      if (!Number.isSafeInteger(byteLength) || byteLength > 2_000_000) return internalError();
      headers.set("Content-Length", contentLength);
    }
    return new Response(upstream.body, {
      status: 200,
      headers,
    });
  };
}

function normalizedBaseUrl(value: string): URL {
  const base = new URL(value);
  if (base.protocol !== "http:" && base.protocol !== "https:") {
    throw new Error("API_BASE_URL must use HTTP or HTTPS");
  }
  return base;
}

function normalizedMediaType(value: string | null): string {
  const candidate = (value ?? "").split(";", 1)[0] ?? "";
  return ALLOWED_MEDIA_TYPES.has(candidate) ? candidate : "image/webp";
}

function legacyNotFound(cacheControl: string | null = null): Response {
  return fixedTextResponse(JSON.stringify({ detail: NOT_FOUND_DETAIL }), 404, "application/json", cacheControl);
}

// Короткий публичный кэш отказа из API передаётся nginx и браузеру: иначе
// каждая неудачная картинка запрашивалась заново и ждала тот же таймаут.
function notFoundCacheControl(value: string | null): string | null {
  const directives = (value ?? "").toLowerCase().split(",").map((item) => item.trim());
  const maxAge = directives.map((item) => /^max-age=([0-9]+)$/.exec(item)?.[1]).find(Boolean);
  if (!directives.includes("public") || maxAge === undefined) return null;
  return `public, max-age=${Math.min(Number(maxAge), NOT_FOUND_MAX_AGE_SECONDS)}`;
}

function internalError(): Response {
  return fixedTextResponse("Internal Server Error", 500, "text/plain; charset=utf-8");
}

export function legacyEmojiRouteNotFound(): Response {
  return fixedTextResponse('{"detail":"Not Found"}', 404, "application/json");
}

function fixedTextResponse(body: string, status: number, contentType: string,
  cacheControl: string | null = null): Response {
  const headers = new Headers({
    "Content-Length": String(new TextEncoder().encode(body).byteLength),
    "Content-Type": contentType,
  });
  if (cacheControl !== null) headers.set("Cache-Control", cacheControl);
  return new Response(body, { status, headers });
}
