import { readFile, mkdir, writeFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";
import { resolve } from "node:path";

const rows = JSON.parse(await readFile(resolve(process.env.NEXT_DIST_DIR??".next","diagnostics/route-bundle-stats.json"), "utf8"));
const output = process.env.BUNDLE_REPORT ?? "reports/bundle-budget.json";

// Production firstLoad after splitting SVG renderers: ordinary routes ~157 KiB,
// comparison ~167 KiB, publication ~179 KiB. Chart ceilings leave ~15%;
// ordinary routes retain the existing stricter ceiling.
// The mobile gate separately counts all initially requested dynamic chunks.
const DEFAULT_BUDGET = 170 * 1024;
const CHART_BUDGET = 206 * 1024;
const CHART_ROUTES = new Set(["/publications/[id]"]);

const results = [];
for (const row of rows) {
  const chunks = [...new Set(row.firstLoadChunkPaths)];
  const sizes = await Promise.all(chunks.map(async (file) => ({ file, gzipBytes: gzipSync(await readFile(file), { level: 9 }).length })));
  const gzipBytes = sizes.reduce((sum, chunk) => sum + chunk.gzipBytes, 0);
  const budgetBytes = row.route === "/compare" ? 192 * 1024 : CHART_ROUTES.has(row.route) ? CHART_BUDGET : DEFAULT_BUDGET;
  results.push({ route: row.route, gzipBytes, budgetBytes, passed: gzipBytes <= budgetBytes, chunks: sizes });
}
const report = { generatedAt: new Date().toISOString(), producer: "next build diagnostics + per-chunk gzip level 9",scope:"Static firstLoad diagnostic only. Required initially loaded dynamic chart chunks are also measured by mobile-performance.mts; this report alone cannot establish the initial-network JS gate.", results, gate: results.every((row) => row.passed) ? "PASS" : "NO-GO" };
await mkdir(resolve(output, ".."), { recursive: true });
await writeFile(output, JSON.stringify(report, null, 2) + "\n");
console.log(results.map((row) => `${row.route}: ${(row.gzipBytes / 1024).toFixed(2)} KiB / ${(row.budgetBytes / 1024).toFixed(0)} KiB ${row.passed ? "PASS" : "FAIL"}`).join("\n"));
if (report.gate !== "PASS") process.exitCode = 1;
