import { readFile, mkdir, writeFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";
import { resolve } from "node:path";

const rows = JSON.parse(await readFile(resolve(process.env.NEXT_DIST_DIR??".next","diagnostics/route-bundle-stats.json"), "utf8"));
const output = process.env.BUNDLE_REPORT ?? "reports/bundle-budget.json";

// Measured against origin/fixin before this change: home 164 KiB, statistics
// 206 KiB, publication 197 KiB. The new landing and analysis bring these to
// 170, 209 and 236 KiB. Keep route-specific ceilings with about 10% headroom;
// the mobile gate also counts initially requested dynamic chunks.
// October 2026: animate-ui components (Motion via LazyMotion and the slim
// motion/react-m entry) add 17-38 KiB per route; the owner accepted that
// trade for consistent animations. Ceilings keep about 5% headroom over the
// measured 182-261 KiB. /manage is an authenticated admin page.
// /manage 240 KiB: on the deployed 5b9f2c7 it measured 233.4 of 235 KiB; the
// findings page's lazy Combobox/Popover share Base UI internals (Field,
// Dialog) with the admin dialogs, and Turbopack regroups them: 235.1 KiB with
// no findings code in the /manage chunks.
// /manage 260 KiB, October 2026: the login-04 sign-in with InputOTP, the
// data-table for institutions (Base UI Checkbox, filters, paging, bulk
// actions) and the live System tab poller measured 247.8 KiB. Charts stay
// lazy; the admin page is behind authentication and not on the public gate.
// /accounts/[id] 215 KiB, October 2026: the card became a horizontal ribbon of
// sections (client scroll-snap navigation, about 1.5 KiB); the comparison
// slides, their heatmap and the analysis load as separate chunks near the
// viewport. Measured 205.8 KiB, 13.9 KiB of it the weekly trend's animated
// toggle that the page already carried.
const DEFAULT_BUDGET = 205 * 1024;
const ROUTE_BUDGETS = new Map([
  ["/compare", 235 * 1024],
  ["/statistics", 260 * 1024],
  ["/publications/[id]", 275 * 1024],
  ["/manage", 260 * 1024],
  ["/accounts/[id]", 215 * 1024],
]);

const results = [];
for (const row of rows) {
  const chunks = [...new Set(row.firstLoadChunkPaths)];
  const sizes = await Promise.all(chunks.map(async (file) => ({ file, gzipBytes: gzipSync(await readFile(file), { level: 9 }).length })));
  const gzipBytes = sizes.reduce((sum, chunk) => sum + chunk.gzipBytes, 0);
  const budgetBytes = ROUTE_BUDGETS.get(row.route) ?? DEFAULT_BUDGET;
  results.push({ route: row.route, gzipBytes, budgetBytes, passed: gzipBytes <= budgetBytes, chunks: sizes });
}
const report = { generatedAt: new Date().toISOString(), producer: "next build diagnostics + per-chunk gzip level 9",scope:"Static firstLoad diagnostic only. Required initially loaded dynamic chart chunks are also measured by mobile-performance.mts; this report alone cannot establish the initial-network JS gate.", results, gate: results.every((row) => row.passed) ? "PASS" : "NO-GO" };
await mkdir(resolve(output, ".."), { recursive: true });
await writeFile(output, JSON.stringify(report, null, 2) + "\n");
console.log(results.map((row) => `${row.route}: ${(row.gzipBytes / 1024).toFixed(2)} KiB / ${(row.budgetBytes / 1024).toFixed(0)} KiB ${row.passed ? "PASS" : "FAIL"}`).join("\n"));
if (report.gate !== "PASS") process.exitCode = 1;
