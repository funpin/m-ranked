import type { components } from "../../contracts/openapi/m-ranked-v1-client";
import { hourlyReach, typeRows, type DashboardPeriod, type DashboardPlatform, type TimingSource } from "./compare-dashboard";

/** Время и форматы одного вуза: догружаются только для выделенных вузов,
 *  поэтому общий ответ панели не растёт. */
export type InstitutionTiming = components["schemas"]["ComparisonInstitutionTiming"];

/** Медиана часа из одного-двух постов — шум: такие часы линия вуза пропускает. */
export const OVERLAY_MIN_POSTS = 3;

export async function fetchInstitutionTiming(id: string, period: DashboardPeriod, signal?: AbortSignal,
  fetcher: typeof fetch = fetch): Promise<InstitutionTiming> {
  const response = await fetcher(`/api/v1/compare/institutions/${encodeURIComponent(id)}/timing?period=${period}`,
    { headers: { accept: "application/json" }, signal });
  if (!response.ok) throw new Error(`timing ${id}: HTTP ${response.status}`);
  const body = await response.json() as InstitutionTiming;
  if (!Array.isArray(body?.timing) || !Array.isArray(body?.types)) throw new Error(`timing ${id}: unexpected body`);
  return body;
}

/** Медиана просмотров за сутки по часу выхода у вуза; редкие часы — пропуск. */
export function hourlyOverlay(source: TimingSource, platform: DashboardPlatform, minPosts = OVERLAY_MIN_POSTS) {
  return hourlyReach(source, platform).map((row) => ({ ...row, views24: row.posts >= minPosts ? row.views24 : null }));
}

/** Строки форматов в одном порядке для всех вузов сразу: порядок и состав — по
 *  панели, у каждого выделенного вуза — своя доля постов и медиана просмотров. */
export function typeComparison(base: TimingSource, platform: DashboardPlatform,
  overlays: readonly { id: string; source: TimingSource }[]) {
  const byOverlay = overlays.map(({ id, source }) => ({ id, rows: new Map(typeRows(source, platform).map((row) => [row.code, row])) }));
  return typeRows(base, platform).map((row) => {
    const point: Record<string, string | number | null> = { ...row };
    for (const { id, rows } of byOverlay) {
      const own = rows.get(row.code);
      point[`share_${id}`] = own?.share ?? 0;
      point[`posts_${id}`] = own?.posts ?? 0;
      point[`views_${id}`] = own?.views24 ?? null;
    }
    return point;
  });
}
