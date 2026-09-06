export class ContinuationError extends Error {}

/** Assemble bounded responses while refusing mixed revisions or repeated pages. */
export async function collectPages<T extends { datasetRevision: number }>(
  request: (cursor?: string) => Promise<T>, next: (page: T) => string | null,
): Promise<T[]> {
  for (let attempt = 0; attempt < 2; attempt++) {
    const pages: T[] = [];
    const seen = new Set<string>();
    let cursor: string | undefined;
    try {
      do {
        const page = await request(cursor);
        if (pages.length && page.datasetRevision !== pages[0]!.datasetRevision) throw new ContinuationError("Dataset changed while reading continuation");
        pages.push(page);
        cursor = next(page) ?? undefined;
        if (cursor) {
          if (seen.has(cursor)) throw new Error("API returned a repeated continuation cursor");
          seen.add(cursor);
        }
        if (pages.length > 100) throw new Error("Continuation exceeded the request safety bound; no partial result was returned");
      } while (cursor);
      return pages;
    } catch (error) {
      const staleCursor = cursor && error instanceof Error && "status" in error && error.status === 400;
      if (attempt === 0 && (error instanceof ContinuationError || staleCursor)) continue;
      throw error;
    }
  }
  throw new ContinuationError("Dataset changed repeatedly");
}

export function uniqueRows<T>(rows: T[], identity: (row: T) => string | number): T[] {
  if (new Set(rows.map(identity)).size !== rows.length) throw new Error("API continuation returned duplicate identities");
  return rows;
}
