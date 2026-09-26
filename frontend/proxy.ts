import { NextResponse, type NextRequest } from "next/server";
import { legacyQueryErrors } from "./lib/legacy-validation";
import { legacyDetailError } from "./lib/legacy-detail-error";
import { prepareManage } from "./lib/manage-facade";
import { publicationCacheHeader } from "./lib/cache-policy";
import { overviewRedirect } from "./lib/overview-redirect";

// Строгая политика с одноразовым nonce. Инлайн-скрипты разрешены только со
// своим nonce, поэтому внедрённый в разметку скрипт не выполнится. Стили
// остаются с 'unsafe-inline': Recharts печатает <style> в разметку страницы,
// и перевод их на nonce — отдельная работа (владелец: фронтенд, до 2026-12-31).
function policy(nonce: string | null): string {
  const script = nonce === null
    ? "'self' 'unsafe-inline'"
    : `'self' 'nonce-${nonce}' 'strict-dynamic'${process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : ""}`;
  return [
    "default-src 'self'",
    `script-src ${script}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'self'",
    "frame-src 'none'",
    "manifest-src 'self'",
    "worker-src 'self' blob:",
    "upgrade-insecure-requests",
  ].join("; ");
}

function nonceValue(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return btoa(String.fromCharCode(...bytes));
}

export async function proxy(request: NextRequest) {
  const detail = legacyQueryErrors(request.nextUrl);
  if (detail.length) return NextResponse.json({ detail }, { status: 422, headers: { "Cache-Control": "no-store" } });
  const moved = overviewRedirect(new URL(request.nextUrl.href));
  if (moved) return NextResponse.redirect(moved, 308);
  let cacheSeconds: string | null = null;
  if(request.method === "GET") {
    const apiOrigin = process.env.API_BASE_URL ?? "http://127.0.0.1:8080";
    const failure = await legacyDetailError(new URL(request.nextUrl.href), apiOrigin);
    if(failure) return failure;
    cacheSeconds = await publicationCacheHeader(new URL(request.nextUrl.href), apiOrigin);
  }
  const requestHeaders = new Headers(request.headers);
  // Заголовки политики и nonce приходят только отсюда: присланные клиентом
  // удаляются, иначе чужой заголовок задал бы странице предсказуемый nonce.
  for (const key of ["x-nonce", "content-security-policy", "content-security-policy-report-only"]) requestHeaders.delete(key);
  requestHeaders.set("x-mranked-path", request.nextUrl.pathname);
  const administrative = request.nextUrl.pathname === "/manage" || request.nextUrl.pathname.startsWith("/manage/");
  // Nonce выдаётся только там, где страница рисуется на каждый запрос. Публичные
  // страницы отдаются из кэша: nonce в них устарел бы раньше, чем дошёл до
  // читателя, поэтому у них пока прежняя политика без строгого script-src.
  const nonce = administrative ? nonceValue() : null;
  const strict = policy(nonce);
  if (nonce !== null) {
    requestHeaders.set("x-nonce", nonce);
    // Next читает политику из заголовка запроса и сам проставляет nonce своим скриптам.
    requestHeaders.set("content-security-policy", strict);
  }
  const response = request.method === "GET" && administrative
    ? await prepareManage(request, requestHeaders)
    : NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", strict);
  // Срок готовой страницы в кэше nginx; до клиента заголовок не доходит.
  if (cacheSeconds && !administrative) response.headers.set("X-Accel-Expires", cacheSeconds);
  return response;
}

export const config = { matcher: ["/((?!api|_next/static|_next/image|favicon.ico|emoji).*)"] };
