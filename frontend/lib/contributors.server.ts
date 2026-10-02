import { readFile } from "node:fs/promises";
import path from "node:path";
import { BUNDLED_CONTRIBUTORS, isContributor, type Contributor } from "@/lib/contributor";

// Файл обновляется раз в трое суток: перечитывать его чаще десяти минут незачем.
const TTL_MS = 10 * 60 * 1000;
let cached: { at: number; value: Contributor[] } | null = null;

/** Каталог, который наполняет таймер m-ranked-target-contributors. */
export function contributorsDirectory(): string | null {
  const value = process.env.MRANKED_CONTRIBUTORS_DIR?.trim();
  return value && path.isAbsolute(value) ? value : null;
}

/** Авторы с сервера; без файла или при ошибке — список из сборки. */
export async function readContributors(now = Date.now()): Promise<Contributor[]> {
  if (cached && now - cached.at < TTL_MS) return cached.value;
  let value = BUNDLED_CONTRIBUTORS;
  const directory = contributorsDirectory();
  if (directory) {
    try {
      const parsed: unknown = JSON.parse(await readFile(path.join(directory, "contributors.json"), "utf8"));
      if (Array.isArray(parsed) && parsed.length > 0 && parsed.length <= 16 && parsed.every(isContributor)) value = parsed;
    } catch { /* Файла ещё нет или он битый: остаётся список из сборки. */ }
  }
  cached = { at: now, value };
  return value;
}

/** Для тестов: сбросить прочитанный список. */
export function resetContributorsCache() { cached = null; }
