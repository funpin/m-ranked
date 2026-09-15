import type { NextRequest } from "next/server";
import { manageSession, submitManage } from "../../../lib/manage-facade";

export const dynamic = "force-dynamic";
const SESSION = new Set(["/manage/sign-in", "/manage/sign-out"]);

export async function POST(request: NextRequest) {
  return SESSION.has(request.nextUrl.pathname) ? manageSession(request) : submitManage(request);
}
