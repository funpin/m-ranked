# @mranked/legacy-chart 0.1.0

Local Canvas2D line/bar renderer for M-Ranked's legacy chart contract. The workspace dependency is recorded in the pnpm lockfile. Chart routes dynamically import this package through `lib/chart-line.ts` and `lib/chart-history.ts`; Chart.js imports in the package are TypeScript-only. The pinned @kurkle/color 0.3.4 utility reproduces the legacy active-bar color transformation.

The supported subset includes numeric/category axes, independent left/right scales, null gaps, tension, fills, point/bar styles, dataset visibility, pointer/keyboard selection, and the legacy tooltip fields. Every supplied non-null sample is drawn. Sampling of long publication histories remains an explicit application operation, with the original observations retained in the table.

`update()` recalculates changed data/labels/scales. `render()` redraws axes and tooltip using the current line data plane; small bar plots also redraw active bar styles; it is used for theme changes and keyboard selection. Large comparisons cache at most 16 raster groups within a 16 MiB extra bitmap budget per chart. A changed axis invalidates those groups; changed visibility at the same scale rebuilds only its group. Small charts do not allocate group caches. `destroy()` releases the resize observer, event listeners and bitmap. This is a purpose-specific renderer, not a general replacement for the entire Chart.js API.

The Chart.js 4.4.7 geometry and tooltip behavior inform compatibility; see `THIRD_PARTY_LICENSES.md`. Approval depends on unmasked visual captures, data/interaction checks and production network/performance measurements. A small package alone does not establish parity or meet the full release gate.
