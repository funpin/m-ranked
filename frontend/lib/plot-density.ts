/** Pixel-space presentation only. Underlying timestamps and gap counts remain intact. */
export type PixelInterval = { left: number; right: number };

export function mergePixelIntervals(ranges: readonly PixelInterval[], distance: number): PixelInterval[] {
  const merged: PixelInterval[] = [];
  for (const range of [...ranges].sort((a, b) => a.left - b.left || a.right - b.right)) {
    const previous = merged.at(-1);
    if (previous && range.left <= previous.right + distance) previous.right = Math.max(previous.right, range.right);
    else merged.push({ ...range });
  }
  return merged;
}

export function clusterPixelMarks<T extends { x: number }>(marks: readonly T[], distance: number):
  { x: number; marks: T[] }[] {
  const groups: { x: number; marks: T[] }[] = [];
  for (const mark of [...marks].sort((a, b) => a.x - b.x)) {
    const previous = groups.at(-1);
    if (previous && mark.x - previous.marks[0]!.x < distance) {
      previous.marks.push(mark);
      previous.x = previous.marks.reduce((sum, item) => sum + item.x, 0) / previous.marks.length;
    } else groups.push({ x: mark.x, marks: [mark] });
  }
  return groups;
}
