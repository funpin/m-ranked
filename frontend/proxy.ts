import { NextResponse, type NextRequest } from "next/server";
import { legacyQueryErrors } from "./lib/legacy-validation";
import { legacyDetailError } from "./lib/legacy-detail-error";
import { prepareManage } from "./lib/manage-facade";

export async function proxy(request: NextRequest) {
  const detail = legacyQueryErrors(request.nextUrl);
  if (detail.length) return NextResponse.json({ detail }, { status: 422, headers: { "Cache-Control": "no-store" } });
  if(request.method === "GET") {
    const failure = await legacyDetailError(new URL(request.nextUrl.href), process.env.API_BASE_URL ?? "http://127.0.0.1:8080");
    if(failure) return failure;
  }
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-mranked-path", request.nextUrl.pathname);
  if (request.method === "GET" && (request.nextUrl.pathname === "/manage" || request.nextUrl.pathname.startsWith("/manage/")))
    return prepareManage(request, requestHeaders);
  return NextResponse.next({ request: { headers: requestHeaders } });
}

export const config = { matcher: ["/((?!api|_next/static|_next/image|favicon.ico|emoji).*)"] };
