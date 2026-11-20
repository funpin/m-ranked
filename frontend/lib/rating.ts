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

/** Чья сторона таблицы: наш прогноз или опубликованный факт. */
export type RatingView = "forecast" | "fact";

export const RATING_VIEWS = [
  { value: "forecast", label: "Прогноз" },
  { value: "fact", label: "Факт" },
] as const satisfies readonly { value: RatingView; label: string }[];

export function normalizeView(raw: string | string[] | undefined): RatingView {
  return single(raw) === "fact" ? "fact" : "forecast";
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

/** Место текущей стороны: прогнозное или фактическое (null — факта нет). */
export function viewRank(cell: RatingForecastCell, view: RatingView): number | null {
  return view === "fact" ? cell.actualRank : cell.rank;
}

export function viewScore(cell: RatingForecastCell, view: RatingView): number | null {
  return view === "fact" ? cell.actualScore : cell.score;
}

/** Δ: на сколько мест выше места прошлого опубликованного месяца — по прогнозу или по факту. */
export function monthShift(cell: RatingForecastCell, view: RatingView): number | null {
  const current = viewRank(cell, view);
  return cell.baseRank === null || current === null ? null : cell.baseRank - current;
}

/** ±: на сколько мест другая сторона выше текущей. В прогнозе — факт против
 *  прогноза, в факте — прогноз против факта; плюс — место лучше. */
export function placeGap(cell: RatingForecastCell, view: RatingView): number | null {
  if (cell.actualRank === null) return null;
  return view === "fact" ? cell.actualRank - cell.rank : cell.rank - cell.actualRank;
}

export function signed(value: number): string {
  return value > 0 ? `+${value}` : value < 0 ? `−${-value}` : "0";
}

export function rowsFor(rows: RatingForecastRow[], category: RatingCategory, view: RatingView = "forecast"): RatingForecastRow[] {
  const place = (row: RatingForecastRow) => viewRank(row.categories[category], view) ?? Number.POSITIVE_INFINITY;
  return [...rows].sort((left, right) => place(left) - place(right) || left.name.localeCompare(right.name, "ru"));
}

export function scatterPoints(rows: RatingForecastRow[], category: RatingCategory) {
  return rows.flatMap((row) => {
    const cell = row.categories[category];
    return cell.actualRank === null ? [] : [{ name: row.shortName ?? row.name, predicted: cell.rank, actual: cell.actualRank }];
  });
}

const MONTH_NAMES = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август",
  "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"] as const;

/** «2026-10» → «Октябрь 2026»: так же называет месяцы официальный рейтинг. */
export function monthLabel(month: string): string {
  const [year, number] = month.split("-");
  return `${MONTH_NAMES[Number(number) - 1]} ${year}`;
}

/** Положение места на шкале 1…total в процентах слева: первое место — край шкалы. */
export function stripPosition(rank: number, total: number): number {
  if (total <= 1) return 0;
  return Math.min(100, Math.max(0, ((rank - 1) / (total - 1)) * 100));
}

/** Ячейка на неполных данных: помечается «*» перед числом. Нет аккаунта — не
 *  неполнота: 0, как в официальном рейтинге. */
export function isIncomplete(cell: RatingForecastCell): boolean {
  return cell.source === "fallback" || cell.source === "partial" || cell.source === "source_zero";
}

/** Почему в ячейке не обычный расчёт по формуле; null — обычный. */
export function sourceNote(cell: RatingForecastCell, basePeriod: string): string | null {
  switch (cell.source) {
    case "fallback": return `нет полных данных — взят балл за ${basePeriod.toLowerCase()}`;
    case "partial": return "часть площадок — по баллу прошлого месяца";
    case "no_account": return "аккаунта нет — 0, как в официальном рейтинге";
    case "source_zero": return "рейтинг не учитывает этот канал: 0 два месяца подряд";
    default: return null;
  }
}
