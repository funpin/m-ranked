/** «Наш рейтинг»: подписи, статус месяца и форматирование порогов формулы. Без React,
 *  чтобы страница и тесты считали одинаково. */
import type { OwnRating, OwnRatingPlatform, OwnRatingRow } from "./types";

export const OWN_PLATFORMS = [
  { key: "telegram", label: "Telegram" },
  { key: "vk", label: "VK" },
  { key: "max", label: "MAX" },
  { key: "rutube", label: "Rutube" },
] as const satisfies readonly { key: keyof OwnRatingRow["platforms"]; label: string }[];

export type OwnPlatformKey = (typeof OWN_PLATFORMS)[number]["key"];

function moscowDay(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit", timeZone: "Europe/Moscow" }).format(new Date(iso));
}

export function ownStatusLine(own: Pick<OwnRating, "status" | "asOf">): string {
  switch (own.status) {
    case "running":
      return `Месяц не закончен, данные на ${moscowDay(own.asOf)}`;
    case "final":
      return "Месяц закончен, итог уточняется до 7-го числа: просмотры последних постов ещё докапливаются";
    case "published":
      return "Итог месяца";
    case "retrospective":
      return "Ретроспективный расчёт";
  }
}

/** Число в подписи формулы: без лишних нулей, с запятой. */
export function plain(value: number): string {
  return new Intl.NumberFormat("ru-RU", { maximumSignificantDigits: 3 }).format(value);
}

export function percent(value: number): string {
  return `${plain(value * 100)} %`;
}

/** Причина «*»: какой площадки не хватает и почему. */
export function partialNote(row: Pick<OwnRatingRow, "platforms">): string | null {
  const notes = OWN_PLATFORMS.flatMap(({ key, label }) => {
    const item = row.platforms[key];
    if (item.source === "no_data") return [`${label}: собрано слишком мало дней, в среднее не входит`];
    if (item.source === "partial") return [`${label}: собрана часть месяца`];
    return [];
  });
  return notes.length ? notes.join("; ") : null;
}

/** Подсказка к баллу площадки: части балла и исходные числа. */
export function platformTitle(item: OwnRatingPlatform): string {
  switch (item.source) {
    case "no_account": return "Аккаунта нет — 0 баллов";
    case "no_posts": return "За месяц ни одной публикации — 0 баллов";
    case "no_data": return "Собрано слишком мало дней месяца — площадка в среднее не входит";
  }
  const parts: string[] = [];
  if (item.subscores) {
    parts.push(`регулярность ${item.subscores.activity.toFixed(0)}, охват ${item.subscores.reach.toFixed(0)}, вовлечённость ${item.subscores.engagement.toFixed(0)}`);
  }
  const metrics = item.metrics;
  if (metrics) {
    parts.push(`публикаций ${metrics.posts}, дней с публикациями ${metrics.activeDays} из ${Math.round(metrics.coveredDays)}`);
    if (metrics.reach !== null) parts.push(`просмотров поста на студента ${plain(metrics.reach)}`);
    if (metrics.erv !== null) parts.push(`вовлечённость ${percent(metrics.erv)}`);
  }
  if (item.source === "partial") parts.push("собрана часть месяца");
  return parts.join("; ");
}

/** Что не засчитано на площадке — осторожной формулировкой (ADR-006). */
export function removedNote(item: OwnRatingPlatform): string | null {
  const metrics = item.metrics;
  if (!metrics) return null;
  const notes: string[] = [];
  if (metrics.removedInteractions > 0) notes.push(`не засчитано реакций и комментариев: ${metrics.removedInteractions.toLocaleString("ru-RU")}`);
  if (metrics.removedViews > 0) notes.push(`просмотров: ${metrics.removedViews.toLocaleString("ru-RU")}`);
  if (metrics.evenCapped) notes.push("вовлечённость засчитана не выше медианы площадки");
  return notes.length ? `${notes.join(", ")} — признаки статистически необычной активности` : null;
}

/** На сколько мест вуз выше (+) или ниже (−) без очистки, чем с ней. */
export function rawShift(row: Pick<OwnRatingRow, "rank" | "rawRank">): number {
  return row.rank - row.rawRank;
}
