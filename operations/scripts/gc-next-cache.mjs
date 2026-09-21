#!/usr/bin/env node

import { lstat, readdir, realpath, unlink } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import path from "node:path";

const DEFAULTS = Object.freeze({
  maxAgeSeconds: 3_600,
  maxBytes: 128 * 1024 * 1024,
  targetBytes: 96 * 1024 * 1024,
});

function positiveInteger(name, value) {
  if (!Number.isSafeInteger(value) || value <= 0) throw new RangeError(`${name} must be a positive safe integer`);
  return value;
}

async function directoryWithoutSymlink(directory, allowMissing) {
  let stat;
  try {
    stat = await lstat(directory);
  } catch (error) {
    if (allowMissing && error?.code === "ENOENT") return false;
    throw error;
  }
  if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error(`refusing non-directory or symlink cache path: ${directory}`);
  return true;
}

async function inventory(directory) {
  const files = [];
  const walk = async (current) => {
    for (const item of await readdir(current, { withFileTypes: true })) {
      const itemPath = path.join(current, item.name);
      if (item.isDirectory()) await walk(itemPath);
      else if (item.isFile()) {
        const stat = await lstat(itemPath);
        files.push({ path: itemPath, dev: stat.dev, ino: stat.ino, mtimeMs: stat.mtimeMs, size: stat.size });
      }
      // Symlinks, sockets and devices are never followed or removed.
    }
  };
  await walk(directory);
  return files;
}

async function unlinkIfUnchanged(file) {
  try {
    const current = await lstat(file.path);
    if (!current.isFile() || current.dev !== file.dev || current.ino !== file.ino || current.size !== file.size || current.mtimeMs !== file.mtimeMs) return 0;
    await unlink(file.path);
    return file.size;
  } catch (error) {
    if (error?.code === "ENOENT") return 0;
    throw error;
  }
}

/** Delete only regular files below <cacheRoot>/fetch-cache. */
export async function collectNextFetchCache(cacheRoot, options = {}) {
  const maxAgeSeconds = positiveInteger("maxAgeSeconds", options.maxAgeSeconds ?? DEFAULTS.maxAgeSeconds);
  const maxBytes = positiveInteger("maxBytes", options.maxBytes ?? DEFAULTS.maxBytes);
  const targetBytes = positiveInteger("targetBytes", options.targetBytes ?? DEFAULTS.targetBytes);
  if (targetBytes > maxBytes) throw new RangeError("targetBytes must not exceed maxBytes");
  const nowMs = options.nowMs ?? Date.now();
  positiveInteger("nowMs", nowMs);

  if (!await directoryWithoutSymlink(cacheRoot, true)) return { beforeBytes: 0, afterBytes: 0, scannedFiles: 0, removedFiles: 0, removedBytes: 0 };
  const resolvedRoot = await realpath(cacheRoot);
  const fetchDirectory = path.join(resolvedRoot, "fetch-cache");
  if (!await directoryWithoutSymlink(fetchDirectory, true)) return { beforeBytes: 0, afterBytes: 0, scannedFiles: 0, removedFiles: 0, removedBytes: 0 };
  const resolvedFetch = await realpath(fetchDirectory);
  if (resolvedFetch !== fetchDirectory) throw new Error(`refusing redirected fetch cache path: ${fetchDirectory}`);

  const files = await inventory(fetchDirectory);
  const beforeBytes = files.reduce((total, file) => total + file.size, 0);
  let afterBytes = beforeBytes;
  let removedBytes = 0;
  let removedFiles = 0;
  const removed = new Set();
  const oldestFirst = [...files].sort((left, right) => left.mtimeMs - right.mtimeMs || left.path.localeCompare(right.path));

  for (const file of oldestFirst) {
    if (nowMs - file.mtimeMs < maxAgeSeconds * 1_000) continue;
    const bytes = await unlinkIfUnchanged(file);
    if (bytes > 0) {
      removed.add(file.path); removedFiles++; removedBytes += bytes; afterBytes -= bytes;
    }
  }
  if (afterBytes > maxBytes) {
    for (const file of oldestFirst) {
      if (afterBytes <= targetBytes) break;
      if (removed.has(file.path)) continue;
      const bytes = await unlinkIfUnchanged(file);
      if (bytes > 0) {
        removedFiles++; removedBytes += bytes; afterBytes -= bytes;
      }
    }
  }

  return { beforeBytes, afterBytes, scannedFiles: files.length, removedFiles, removedBytes };
}

function envInteger(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  if (!/^[1-9][0-9]*$/.test(raw)) throw new Error(`${name} must be a positive integer`);
  return positiveInteger(name, Number(raw));
}

async function main() {
  const result = await collectNextFetchCache(process.env.MRANKED_WEB_CACHE_ROOT ?? "/var/lib/m-ranked/web-cache", {
    maxAgeSeconds: envInteger("MRANKED_WEB_CACHE_MAX_AGE_SECONDS", DEFAULTS.maxAgeSeconds),
    maxBytes: envInteger("MRANKED_WEB_CACHE_MAX_BYTES", DEFAULTS.maxBytes),
    targetBytes: envInteger("MRANKED_WEB_CACHE_TARGET_BYTES", DEFAULTS.targetBytes),
  });
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((error) => { console.error(error); process.exitCode = 1; });
}
