import { FRESHNESS_MS, type PublicRepresentation, type PublicResponseCache } from "./revision-cache";

export interface BoundedResponseCacheOptions {
  maxBytes: number;
  maxEntries: number;
  ttlMs: number;
  now?: () => number;
}

interface Entry {
  expiresAt: number;
  size: number;
  value: PublicRepresentation;
}

function positiveInteger(name: string, value: number): number {
  if (!Number.isSafeInteger(value) || value <= 0) throw new RangeError(`${name} must be a positive safe integer`);
  return value;
}

function representationSize(value: PublicRepresentation): number {
  let size = Buffer.byteLength(value.body) + 16;
  for (const [name, headerValue] of value.headers) size += Buffer.byteLength(name) + Buffer.byteLength(headerValue) + 8;
  return size;
}

/**
 * Process-local TTL/LRU for revision-addressed public API representations.
 * It deliberately does not persist across releases: a deploy or rollback starts
 * cold, while representationVersion in the key still isolates live releases.
 */
export function createBoundedPublicResponseCache(options: BoundedResponseCacheOptions): PublicResponseCache {
  const maxBytes = positiveInteger("maxBytes", options.maxBytes);
  const maxEntries = positiveInteger("maxEntries", options.maxEntries);
  const ttlMs = positiveInteger("ttlMs", options.ttlMs);
  const now = options.now ?? Date.now;
  const entries = new Map<string, Entry>();
  const pending = new Map<string, Promise<PublicRepresentation>>();
  let bytes = 0;

  function remove(key: string, entry: Entry): void {
    if (entries.delete(key)) bytes -= entry.size;
  }

  function sweepExpired(at: number): void {
    for (const [key, entry] of entries) if (entry.expiresAt <= at) remove(key, entry);
  }

  function store(key: string, value: PublicRepresentation, at: number): void {
    const size = representationSize(value);
    const replaced = entries.get(key);
    if (replaced) remove(key, replaced);
    if (size > maxBytes) return;
    entries.set(key, { expiresAt: at + ttlMs, size, value });
    bytes += size;
    while (entries.size > maxEntries || bytes > maxBytes) {
      const oldestKey = entries.keys().next().value as string | undefined;
      if (oldestKey === undefined) break;
      remove(oldestKey, entries.get(oldestKey)!);
    }
  }

  return {
    async load(parts, _tags, produce) {
      const key = JSON.stringify(parts);
      const at = now();
      const cached = entries.get(key);
      if (cached && cached.expiresAt > at) {
        // Map insertion order is the LRU order.
        entries.delete(key);
        entries.set(key, cached);
        return cached.value;
      }
      if (cached) remove(key, cached);

      const inFlight = pending.get(key);
      if (inFlight) return inFlight;
      const production = (async () => {
        const value = await produce();
        sweepExpired(now());
        store(key, value, now());
        return value;
      })();
      pending.set(key, production);
      try {
        return await production;
      } finally {
        if (pending.get(key) === production) pending.delete(key);
      }
    },
  };
}

function envPositiveInteger(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  if (!/^[1-9][0-9]*$/.test(raw)) throw new Error(`${name} must be a positive integer`);
  return positiveInteger(name, Number(raw));
}

export function publicResponseCacheFromEnv(): PublicResponseCache {
  return createBoundedPublicResponseCache({
    ttlMs: envPositiveInteger("NEXT_PUBLIC_DATA_CACHE_TTL_MS", FRESHNESS_MS),
    maxEntries: envPositiveInteger("NEXT_PUBLIC_DATA_CACHE_MAX_ENTRIES", 128),
    maxBytes: envPositiveInteger("NEXT_PUBLIC_DATA_CACHE_MAX_BYTES", 16 * 1024 * 1024),
  });
}
