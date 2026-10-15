/** «Рейтинг»: параметры адреса, подписи и порядок строк прогноза. Без React,
 *  чтобы страница и тесты считали одинаково. */
import type { RatingCategory, RatingForecast, RatingForecastCell, RatingForecastRow } from "./types";

export const RATING_CATEGORIES = [
  { value: "social", label: "Соцсети" },
  { value: "max", label: "MAX" },
  { value: "vk", label: "VK" },
  { value: "rutube", label: "Rutube" },
] as const satisfies readonly { value: RatingCategory; label: string }[];

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

function single(raw: string | string[] | undefined): string | undefined {
  return Array.isArray(raw) ? raw[0] : raw;
}

export function normalizeCategory(raw: string | string[] | undefined): RatingCategory {
  const value = single(raw);
  return RATING_CATEGORIES.find((item) => item.value === value)?.value ?? "social";
}

export function normalizeMonth(raw: string | string[] | undefined): string | null {
  const value = single(raw);
  return value && MONTH.test(value) ? value : null;
}

function moscowDay(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit", timeZone: "Europe/Moscow" }).format(new Date(iso));
}

export function statusLine(forecast: Pick<RatingForecast, "status" | "asOf" | "early">): string {
  switch (forecast.status) {
    case "running":
      return `Месяц не закончен, данные на ${moscowDay(forecast.asOf)}${forecast.early ? " — слишком рано для уверенной оценки" : ""}`;
    case "final":
      return "Итоговый прогноз: месяц закончен, официального списка ещё нет";
    case "published":
      return "Опубликовано — прогноз против факта";
    case "retrospective":
      return "Ретроспективный расчёт, не прогноз до публикации";
  }
}

export function hasActual(forecast: Pick<RatingForecast, "status">): boolean {
  return forecast.status === "published" || forecast.status === "retrospective";
}

export function rankLabel(cell: RatingForecastCell): string {
  return cell.rankBest === cell.rankWorst ? String(cell.rank) : `${cell.rank} (${cell.rankBest}–${cell.rankWorst})`;
}

export function rankDelta(cell: RatingForecastCell): number | null {
  return cell.baseRank === null ? null : cell.baseRank - cell.rank;
}

export function rowsFor(rows: RatingForecastRow[], category: RatingCategory): RatingForecastRow[] {
  return [...rows].sort((left, right) => left.categories[category].rank - right.categories[category].rank
    || left.name.localeCompare(right.name, "ru"));
}

export function scatterPoints(rows: RatingForecastRow[], category: RatingCategory) {
  return rows.flatMap((row) => {
    const cell = row.categories[category];
    return cell.actualRank === null ? [] : [{ name: row.shortName ?? row.name, predicted: cell.rank, actual: cell.actualRank }];
  });
}
