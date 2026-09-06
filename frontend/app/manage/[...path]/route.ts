import type { NextRequest } from "next/server";
import { submitManage } from "../../../lib/manage-facade";

export const dynamic = "force-dynamic";
export async function POST(request: NextRequest) { return submitManage(request); }
