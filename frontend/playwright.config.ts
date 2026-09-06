import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/browser",
  fullyParallel: true,
  workers: 2,
  retries: 0,
  outputDir: "test-results/browser",
  reporter: [["list"], ["json", { outputFile: process.env.PLAYWRIGHT_REPORT ?? "test-results/routes-report.json" }]],
  use: { baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:18092", trace: "retain-on-failure" },
  webServer: process.env.PLAYWRIGHT_BASE_URL ? undefined : [
    { command: "node --import tsx tests/api-fixture.mts", url: "http://127.0.0.1:18091/api/v1/revision", reuseExistingServer: false },
    { command: process.env.PLAYWRIGHT_PRODUCTION !== "false" ? "node scripts/browser-server.mjs" : "node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 18092", url: "http://127.0.0.1:18092", reuseExistingServer: false, timeout: 120_000,
      env: { API_BASE_URL: "http://127.0.0.1:18091", NEXT_PUBLIC_DATA_CACHE: "disabled" } },
  ],
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 } } },
  ],
});
