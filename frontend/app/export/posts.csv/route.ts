import { legacyCsv } from "../../../lib/legacy-csv";
export const runtime = "nodejs";
export function GET(request: Request) { return legacyCsv(request, "posts"); }
