import { NextResponse, type NextRequest } from "next/server";
import { timingSafeEqual } from "node:crypto";

const COOKIE = "MRANKED-MANAGE-CSRF";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ACTION = /^\/manage\/(?:channels|institutions|platform-accounts|m-rating\/update|institutions\/[^/]+(?:\/accounts)?|channels\/[^/]+\/(?:enable|disable|delete)|platform-accounts\/[^/]+\/(?:enable|disable|delete|native-id))$/;
// Native same-origin form navigations must retain their Origin. no-referrer
// makes Chromium send Origin:null; same-origin still withholds cross-site URLs.
const NO_STORE = { "Cache-Control": "no-store", "Referrer-Policy": "same-origin" };

function requestOrigin(request: NextRequest): string | null {
  // NextURL normalizes 127.0.0.1 and [::1] to localhost. The browser's Host
  // authority retains the real origin (and port). Forwarded host headers are
  // intentionally ignored; the deployment proxy preserves the request Host.
  const host = request.headers.get("host");
  if (host === null) return request.nextUrl.origin;
  if (!host || /[\s\\/@?#,%]/.test(host)) return null;
  try {
    const origin = new URL(`${request.nextUrl.protocol}//${host}`);
    return ["http:", "https:"].includes(origin.protocol) && !origin.username && !origin.password
      && origin.pathname === "/" && !origin.search && !origin.hash ? origin.origin : null;
  } catch { return null; }
}

function apiUrl(path: string): URL {
  const base = new URL(process.env.API_BASE_URL ?? "http://127.0.0.1:8080");
  if (base.username || base.password || !["http:", "https:"].includes(base.protocol)) throw new Error("Invalid private API URL");
  return new URL(path, base);
}

function forwardingHeaders(request: NextRequest): Headers {
  const result = new Headers({ Accept: "application/json" });
  const authorization = request.headers.get("authorization");
  if (authorization && authorization.length <= 16_384) result.set("Authorization", authorization);
  const token = request.cookies.get(COOKIE)?.value;
  if (token && /^[A-Za-z0-9_-]{1,4096}$/.test(token)) result.set("Cookie", `XSRF-TOKEN=${token}`);
  return result;
}

function failure(status: number, detail: string | object[], authenticate?: string | null): NextResponse {
  const result = NextResponse.json({ detail }, { status, headers: NO_STORE });
  if (status === 401) result.headers.set("WWW-Authenticate", authenticate ?? 'Basic realm="m-ranked"');
  return result;
}

/** This only prepares SSR; Spring independently authenticates and authorizes every read/command. */
export async function prepareManage(request: NextRequest, requestHeaders: Headers): Promise<NextResponse> {
  for (const key of ["x-mranked-csrf", "x-mranked-can-edit", "x-mranked-can-delete"]) requestHeaders.delete(key);
  let upstream: Response;
  try {
    upstream = await fetch(apiUrl("/api/v1/admin/catalog/session"), {
      headers: forwardingHeaders(request), redirect: "error", cache: "no-store", signal: AbortSignal.timeout(5000),
    });
  } catch { return failure(503, "Сервис управления временно недоступен"); }
  if (!upstream.ok) {
    await upstream.body?.cancel();
    return failure(upstream.status, upstream.status === 401 ? "Not authenticated" : "Доступ к управлению недоступен", upstream.headers.get("www-authenticate"));
  }
  const session = await upstream.json().catch(() => null) as { headerName?: string; token?: string; canEdit?: boolean; canDelete?: boolean } | null;
  if (session?.headerName !== "X-XSRF-TOKEN" || !session.token || !/^[A-Za-z0-9_-]{1,4096}$/.test(session.token))
    return failure(502, "Некорректный ответ сервиса управления");
  requestHeaders.set("x-mranked-csrf", session.token);
  requestHeaders.set("x-mranked-can-edit", String(session.canEdit === true));
  requestHeaders.set("x-mranked-can-delete", String(session.canDelete === true));
  const result = NextResponse.next({ request: { headers: requestHeaders } });
  for (const [name, value] of Object.entries(NO_STORE)) result.headers.set(name, value);
  result.cookies.set(COOKIE, session.token, {
    httpOnly: true, sameSite: "strict", secure: request.nextUrl.protocol === "https:", path: "/manage",
  });
  return result;
}

const SAFE_DETAILS = new Set([
  "Укажите название вуза", "Укажите сокращение", "Institution name and short name are required",
  "Укажите хотя бы один аккаунт", "Укажите аккаунт или ссылку", "Не удалось определить аккаунт",
  "Не удалось определить сообщество ВКонтакте", "Telegram-каналы добавляются через основную форму мониторинга",
  "MAX chat_id должен быть числом", "Некорректная ссылка max", "Некорректная ссылка rutube",
  "Не удалось определить max", "Не удалось определить rutube", "Invalid Telegram channel username",
  "Аккаунт должен использовать HTTP(S)-ссылку без учётных данных",
]);

function integer(value: string): string | null {
  const stripped = value.trim();
  if (stripped.length > 4300 || !/^[+-]?\d(?:_?\d)*(?:\.0+)?$/.test(stripped)) return null;
  try { return BigInt(stripped.replaceAll("_", "").replace(/\.0+$/, "")).toString(); } catch { return null; }
}

function authDetail(request: NextRequest): string {
  const authorization = request.headers.get("authorization") ?? "";
  const [scheme, ...rest] = authorization.split(" ");
  if (scheme.toLowerCase() !== "basic") return "Not authenticated";
  const decoded = Buffer.from(rest.join(" "), "base64");
  if (!decoded.includes(58) || decoded.some(byte => byte > 127)) return "Invalid authentication credentials";
  return "Неверный логин или пароль";
}

async function boundedJson(response: Response): Promise<Record<string, unknown> | null> {
  const reader = response.body?.getReader();
  if (!reader) return null;
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > 16_384) { await reader.cancel(); return null; }
      chunks.push(value);
    }
    const result: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    return result !== null && typeof result === "object" && !Array.isArray(result) ? result as Record<string, unknown> : null;
  } catch { return null; } finally { reader.releaseLock(); }
}

/** Session preflight preserves FastAPI's auth-before-validation order. Spring repeats auth, CSRF and RBAC on the command. */
export async function submitManage(request: NextRequest, fetcher: typeof fetch = fetch): Promise<NextResponse> {
  let path: string;
  try { path = decodeURIComponent(request.nextUrl.pathname); } catch { return failure(404, "Not Found"); }
  if (!ACTION.test(path)) return failure(404, "Not Found");
  let authentication: Response;
  try {
    authentication = await fetcher(apiUrl("/api/v1/admin/catalog/session"), {
      headers: forwardingHeaders(request), redirect: "error", cache: "no-store",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(5000)]),
    });
  } catch { return failure(503, "Сервис управления временно недоступен"); }
  if (!authentication.ok) {
    await authentication.body?.cancel();
    return failure(authentication.status, authentication.status === 401 ? authDetail(request) : "Доступ к управлению недоступен", "Basic");
  }
  const session = await boundedJson(authentication);
  if (session?.headerName !== "X-XSRF-TOKEN" || typeof session.token !== "string" || !/^[A-Za-z0-9_-]{1,4096}$/.test(session.token))
    return failure(502, "Некорректный ответ сервиса управления");
  if (session.canEdit !== true || (path.endsWith("/delete") && session.canDelete !== true))
    return failure(403, "Доступ к управлению недоступен");
  const origin = request.headers.get("origin");
  if (origin && origin !== requestOrigin(request)) return failure(403, "Недопустимый источник запроса");
  if ((request.headers.get("content-type") ?? "").split(";", 1)[0].trim().toLowerCase() !== "application/x-www-form-urlencoded" && request.body)
    return failure(415, "Ожидается HTML-форма");
  const maximum = 192 * 1024;
  if (Number(request.headers.get("content-length")) > maximum) return failure(413, "Форма слишком велика");
  const reader = request.body?.getReader();
  let size = 0; const chunks: Uint8Array[] = [];
  try {
    while (reader) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > maximum) { await reader.cancel(); return failure(413, "Форма слишком велика"); }
      chunks.push(value);
    }
  } catch { return failure(400, "Не удалось прочитать форму"); } finally { reader?.releaseLock(); }
  const body = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  const form = new URLSearchParams(new TextDecoder().decode(body));
  const fields: Record<string, string> = Object.create(null);
  for (const [key, value] of form) fields[key] = value;
  const required = path === "/manage/channels" ? ["channel", "csrf_token"]
    : path === "/manage/institutions" ? ["name", "csrf_token"]
    : path === "/manage/platform-accounts" ? ["institution_id", "platform", "reference", "csrf_token"]
    : /^\/manage\/institutions\/[^/]+$/.test(path) ? ["name", "short_name", "csrf_token"]
    : path.endsWith("/native-id") ? ["native_id", "csrf_token"] : ["csrf_token"];
  const errors: object[] = [];
  const invalidInteger = (location: string, name: string, value: string) => errors.push({
    type: "int_parsing", loc: [location, name], msg: "Input should be a valid integer, unable to parse string as an integer", input: value,
  });
  const segments = path.split("/");
  let identifier: string | null | undefined;
  if (segments.length >= 4 && ["institutions", "channels", "platform-accounts"].includes(segments[2])) {
    identifier = integer(segments[3]);
    if (identifier === null) invalidInteger("path", segments[2] === "institutions" ? "institution_id" : segments[2] === "channels" ? "channel_id" : "account_id", segments[3]);
    else { segments[3] = identifier; path = segments.join("/"); }
  }
  for (const key of required) {
    if (!(key in fields)) errors.push({ type: "missing", loc: ["body", key], msg: "Field required", input: null });
    else if (key === "institution_id") {
      const parsed = integer(fields[key]);
      if (parsed === null) invalidInteger("body", key, fields[key]); else fields[key] = parsed;
    }
  }
  if (errors.length) return failure(422, errors);
  const csrf = fields.csrf_token;
  const cookie = request.cookies.get(COOKIE)?.value;
  if (!csrf || !cookie || !/^[A-Za-z0-9_-]{1,4096}$/.test(csrf) || !/^[A-Za-z0-9_-]{1,4096}$/.test(cookie) || csrf.length !== cookie.length
    || !timingSafeEqual(Buffer.from(csrf), Buffer.from(cookie)) || csrf !== session.token)
    return failure(403, "Недействительный защитный токен");
  if (identifier && (BigInt(identifier) < 1n || BigInt(identifier) > 9223372036854775807n))
    return failure(404, segments[2] === "institutions" ? "Вуз не найден" : segments[2] === "channels" ? "Канал не найден" : "Аккаунт не найден");
  const headers = forwardingHeaders(request);
  headers.set("X-XSRF-TOKEN", csrf);
  headers.set("Content-Type", "application/json");
  const correlation = fields.correlation_id ?? crypto.randomUUID();
  if (!UUID.test(correlation)) return failure(400, "Некорректный идентификатор команды");
  headers.set("X-Correlation-Id", correlation);
  const allowed = new Set([...required, "short_name", "title", "url", "telegram", "vk", "max_account", "rutube", "expected_row_version", "expected_account_versions"]);
  for (const key of Object.keys(fields)) if (!allowed.has(key) || key === "csrf_token") delete fields[key];
  let upstream: Response;
  try {
    upstream = await fetcher(apiUrl("/api/v1/admin/catalog/legacy-command"), {
      method: "POST", headers, body: JSON.stringify({ path, fields }), cache: "no-store", redirect: "error",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(900_000)]),
    });
  } catch { return failure(503, "Не удалось получить результат команды. Повторите ту же форму: её идентификатор защищает от повторной записи."); }
  const payload = await boundedJson(upstream);
  if (!upstream.ok) {
    if (upstream.status === 401) return failure(401, authDetail(request), "Basic");
    if (upstream.status === 404) return failure(404, path.startsWith("/manage/channels/") ? "Канал не найден" : path.startsWith("/manage/platform-accounts/") ? "Аккаунт не найден" : "Вуз не найден");
    if (upstream.status === 403) return failure(403, "Доступ к управлению недоступен");
    if (upstream.status === 409) return failure(409, "Данные изменились. Обновите страницу и повторите действие.");
    return failure(upstream.status, upstream.status === 400 && payload?.type === "urn:m-ranked:problem:legacy-form"
      && typeof payload.detail === "string" && SAFE_DETAILS.has(payload.detail) ? payload.detail : "Не удалось выполнить команду");
  }
  if (typeof payload?.location !== "string" || !/^\/manage(?:\?[A-Za-z0-9_=&-]*)?$/.test(payload.location))
    return failure(502, "Некорректный адрес результата команды");
  return new NextResponse(null, { status: 303, headers: { ...NO_STORE, Location: payload.location } });
}
