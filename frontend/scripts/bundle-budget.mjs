import { readFile, mkdir, writeFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";
import { resolve } from "node:path";

const rows = JSON.parse(await readFile(resolve(process.env.NEXT_DIST_DIR??".next","diagnostics/route-bundle-stats.json"), "utf8"));
const output = process.env.BUNDLE_REPORT ?? "evidence/bundle-budget.json";
const results = [];
for (const row of rows) {
  const chunks = [...new Set(row.firstLoadChunkPaths)];
  const sizes = await Promise.all(chunks.map(async (file) => ({ file, gzipBytes: gzipSync(await readFile(file), { level: 9 }).length })));
  const gzipBytes = sizes.reduce((sum, chunk) => sum + chunk.gzipBytes, 0);
  results.push({ route: row.route, gzipBytes, budgetBytes: 170 * 1024, passed: gzipBytes <= 170 * 1024, chunks: sizes });
}
const report = { generatedAt: new Date().toISOString(), producer: "next build diagnostics + per-chunk gzip level 9",scope:"Static firstLoad diagnostic only. Required initially loaded dynamic chart chunks are also measured by mobile-performance.mts; this report alone cannot establish the initial-network JS gate.", results, gate: results.every((row) => row.passed) ? "PASS" : "NO-GO" };
await mkdir(resolve(output, ".."), { recursive: true });
await writeFile(output, JSON.stringify(report, null, 2) + "\n");
console.log(results.map((row) => `${row.route}: ${(row.gzipBytes / 1024).toFixed(2)} KiB ${row.passed ? "PASS" : "FAIL"}`).join("\n"));
if (report.gate !== "PASS") process.exitCode = 1;
