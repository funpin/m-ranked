import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, symlink, utimes, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
// The production collector is intentionally plain ESM so systemd can run it
// directly without a TypeScript runtime.
// @ts-expect-error no declaration file for the operational .mjs module
import { collectNextFetchCache } from "../../operations/scripts/gc-next-cache.mjs";

async function fixture() {
  const parent = await mkdtemp(path.join(os.tmpdir(), "m-ranked-cache-gc-"));
  const active = path.join(parent, "web-cache");
  const fetchCache = path.join(active, "fetch-cache");
  const retired = path.join(parent, "web-cache-retired");
  await mkdir(fetchCache, { recursive: true });
  await mkdir(path.join(retired, "fetch-cache"), { recursive: true });
  return { active, fetchCache, retired };
}

async function put(file: string, body: string, mtimeMs: number) {
  await writeFile(file, body);
  const date = new Date(mtimeMs);
  await utimes(file, date, date);
}

test("cache GC expires only active fetch-cache files and leaves retired caches untouched", async () => {
  const { active, fetchCache, retired } = await fixture();
  await put(path.join(fetchCache, "expired"), "old", 1_000);
  await put(path.join(fetchCache, "fresh"), "new", 9_000);
  const retiredFile = path.join(retired, "fetch-cache", "evidence");
  await put(retiredFile, "keep", 1_000);

  const result = await collectNextFetchCache(active, { nowMs: 10_000, maxAgeSeconds: 5, maxBytes: 100, targetBytes: 80 });
  assert.deepEqual(result, { beforeBytes: 6, afterBytes: 3, scannedFiles: 2, removedFiles: 1, removedBytes: 3 });
  assert.equal(await readFile(path.join(fetchCache, "fresh"), "utf8"), "new");
  assert.equal(await readFile(retiredFile, "utf8"), "keep");
});

test("cache GC applies an oldest-first low-water mark when the byte ceiling is exceeded", async () => {
  const { active, fetchCache } = await fixture();
  await put(path.join(fetchCache, "one"), "1111", 8_000);
  await put(path.join(fetchCache, "two"), "2222", 9_000);
  await put(path.join(fetchCache, "three"), "3333", 9_500);

  const result = await collectNextFetchCache(active, { nowMs: 10_000, maxAgeSeconds: 100, maxBytes: 10, targetBytes: 6 });
  assert.equal(result.beforeBytes, 12);
  assert.equal(result.afterBytes, 4);
  assert.equal(result.removedFiles, 2);
  assert.equal(await readFile(path.join(fetchCache, "three"), "utf8"), "3333");
});

test("cache GC refuses a symlinked active cache root", async () => {
  const { active, retired } = await fixture();
  const redirected = `${active}-link`;
  await symlink(retired, redirected);
  await assert.rejects(() => collectNextFetchCache(redirected), /symlink cache path/);
});
