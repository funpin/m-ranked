import type { components } from "../../contracts/openapi/m-ranked-v1-client";
import { hourlyReach, typeRows, type DashboardPeriod, type DashboardPlatform, type TimingSource } from "./compare-dashboard";

/** Время и форматы одного вуза: догружаются только для выделенных вузов,
 *  поэтому общий ответ панели не растёт. */
export type InstitutionTiming = components["schemas"]["ComparisonInstitutionTiming"];

/** Выделенный вуз с догруженными данными — то, что рисуют графики. */
export type TimingOverlay = { id: string; name: string; color: string; source: TimingSource };

/** Медиана часа из одного-двух постов — шум: такие часы линия вуза пропускает. */
export const OVERLAY_MIN_POSTS = 3;

/** Ключ ряда выделенного вуза в строках графика. */
export const overlayKey = (kind: "share" | "posts" | "views", id: string) => `${kind}_${id}`;

export async function fetchInstitutionTiming(id: string, period: DashboardPeriod): Promise<InstitutionTiming> {
  const response = await fetch(`/api/v1/compare/institutions/${encodeURIComponent(id)}/timing?period=${period}`,
    { headers: { accept: "application/json" } });
  if (!response.ok) throw new Error(`timing ${id}: HTTP ${response.status}`);
  const body = await response.json() as InstitutionTiming;
  if (!Array.isArray(body?.timing) || !Array.isArray(body?.types)) throw new Error(`timing ${id}: unexpected body`);
  return body;
}

/** Медиана просмотров за сутки по часу выхода у вуза; редкие часы — пропуск. */
export function hourlyOverlay(source: TimingSource, platform: DashboardPlatform): (number | null)[] {
  return hourlyReach(source, platform).map((row) => row.posts >= OVERLAY_MIN_POSTS ? row.views24 : null);
}

/** Строки форматов в одном порядке для всех вузов сразу: порядок и состав — по
 *  панели, у каждого выделенного вуза — своя доля постов и медиана просмотров. */
export function typeComparison(base: TimingSource, platform: DashboardPlatform, overlays: readonly TimingOverlay[]) {
  const byOverlay = overlays.map(({ id, source }) => ({ id, rows: new Map(typeRows(source, platform).map((row) => [row.code, row])) }));
  return typeRows(base, platform).map((row) => {
    const point: Record<string, string | number | null> = { ...row };
    for (const { id, rows } of byOverlay) {
      const own = rows.get(row.code);
      point[overlayKey("share", id)] = own?.share ?? 0;
      point[overlayKey("posts", id)] = own?.posts ?? 0;
      point[overlayKey("views", id)] = own?.views24 ?? null;
    }
    return point;
  });
}
