import { many, type SearchValue } from "./params";

const FIRST = "first";

/** Cursors are opaque. Carry the visited path so Previous is the actual prior
 * 20-card page, without offset scans or a misleading arbitrary page jump. */
export function overviewPagination(cursor: string | undefined, rawTrail: SearchValue) {
  const entries = many(rawTrail);
  const valid = entries.length <= 50 && entries[0] === FIRST
    && entries.every((entry, index) => entry.length <= 256 && (index === 0 || entry !== FIRST));
  const trail = cursor ? valid ? entries : [FIRST] : [];
  const previous = trail.at(-1);
  return {
    page: trail.length + 1,
    trail,
    previousCursor: previous === FIRST ? undefined : previous,
    previousTrail: trail.slice(0, -1),
    nextTrail: [...trail, cursor ?? FIRST],
  };
}
