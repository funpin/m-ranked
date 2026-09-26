import type { MetricValue, Period, Platform } from "./types";
import { metricNumber } from "./params";

const integer = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const percentage = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const percentagePrecise = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
});
const timestamp = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export const PLATFORM_LABELS: Record<Platform, string> = {
  all: "Общий",
  telegram: "TG",
  vk: "ВК",
  max: "MAX",
  rutube: "RUTUBE",
};

export const PLATFORM_LONG_LABELS: Record<Platform, string> = {
  all: "Все соцсети",
  telegram: "Telegram",
  vk: "ВКонтакте",
  max: "MAX",
  rutube: "Rutube",
};

export const PERIOD_LABELS: Record<Period, string> = {
  "3h": "3 часа",
  "1d": "Сутки",
  "7d": "Неделя",
  "30d": "Последний месяц",
};

export function formatMetric(value: MetricValue, fraction = false): string {
  const parsed = metricNumber(value);
  if (parsed === null) return "—";
  return (fraction ? decimal : integer).format(parsed);
}

export function formatCoverage(value: MetricValue): string {
  const parsed = metricNumber(value);
  return parsed === null ? "—" : `${decimal.format(parsed * 100)}%`;
}

export function formatPercentage(value: MetricValue, digits: 2 | 3 = 2): string {
  const parsed = metricNumber(value);
  if (parsed === null) return "—";
  return `${(digits === 3 ? percentagePrecise : percentage).format(parsed)}%`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "ещё не рассчитано";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? "неизвестно" : `${timestamp.format(parsed)} МСК`;
}

export function qualityLabel(value: string | null | undefined): string {
  switch ((value ?? "").toLowerCase()) {
    case "exact":
      return "точные данные";
    case "observed":
      return "наблюдаемые данные";
    case "rounded":
      return "округлённые данные";
    case "estimated":
      return "оценка";
    case "missing":
      return "нет данных";
    default:
      return value || "качество не указано";
  }
}

/** Точные значения не требуют предупреждения. Для остальных состояний
 *  возвращаем человекочитаемую подсказку и никогда не показываем сырой код. */
export function qualityHint(value: string | null | undefined): string | undefined {
  const normalized = (value ?? "").toLowerCase();
  if (!normalized || normalized === "exact") return undefined;
  return qualityLabel(value);
}

export function legacyDate(value: string | null | undefined, withZone = false): string {
  if (!value) return "—";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Moscow", day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false }).formatToParts(date);
  const get = (name: string) => parts.find((part) => part.type === name)?.value;
  return `${get("day")}.${get("month")}.${get("year")}, ${get("hour")}:${get("minute")}:${get("second")}${withZone ? " МСК" : ""}`;
}
/** Календарный день публикации по московскому времени: YYYY-MM-DD.
 *  В этих же сутках API считает недельный ряд площадки, поэтому точка графика
 *  и строка таблицы должны разделяться одинаково. */
export function moscowDay(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(date);
  const get = (name: string) => parts.find((part) => part.type === name)?.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Ссылка на сохранённую копию удалённой публикации. MAXSTAT не принимает
 * фильтр даты из URL, поэтому дата остаётся подсказкой интерфейса, а hash
 * помогает перейти к карточке, если она уже загружена на странице канала. */
export function deletedPublicationArchiveUrl(
  platform: Platform,
  deletedAt: string | null,
  externalId: string | null,
  accountUsername?: string | null,
  accountArchiveUrl?: string | null,
): string | null {
  if (!deletedAt || !externalId) return null;
  if (platform === "telegram" && accountUsername) {
    return `https://tgstat.ru/channel/@${encodeURIComponent(accountUsername)}/${encodeURIComponent(externalId)}`;
  }
  if (platform === "max" && accountArchiveUrl?.startsWith("https://maxstat.ru/channel/")) {
    return `${accountArchiveUrl}#${encodeURIComponent(externalId)}`;
  }
  return null;
}
export const PERIOD_SHORT = {"3h":"за 3 часа","1d":"за сутки","7d":"за неделю","30d":"за месяц"} as const;
export function legacyNumber(value: MetricValue) { const n = metricNumber(value); return n === null ? "—" : String(n); }

export function duration(seconds: number | null) {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  const minutes = Math.max(0, Math.round(seconds / 60));
  const days = Math.floor(minutes / 1440), hours = Math.floor(minutes % 1440 / 60);
  return `${days ? `${days} д ` : ""}${hours || days ? `${hours} ч ` : ""}${minutes % 60} мин`;
}
export function publicationLabel(externalId: string | null, platform: Platform) {
  if (!externalId) return "—";
  // Идентификатор поста Telegram хранится с префиксом «m:» — это внутренняя
  // пометка источника, а не часть номера. API отдаёт очищенное значение
  // отдельным полем, но там, где доступен только сырой идентификатор,
  // префикс снимается здесь по тому же правилу.
  if (platform === "telegram") return `№${externalId.startsWith("m:") ? externalId.slice(2) : externalId}`;
  if (platform === "vk" && /^-?\d+_\d+$/.test(externalId)) return `№${externalId.split("_").at(-1)}`;
  return externalId;
}
export function postTypeLabel(value: string) { return ({text:"текст",photo:"фото",video:"видео",album:"альбом",document:"документ",poll:"опрос",webpage:"веб-страница",contact:"контакт",geo:"геолокация",media:"медиа"} as Record<string,string>)[value] ?? value; }

/** На оси значений место ограничено шириной колонки, а показатели доходят до
 *  миллионов. Полное число не влезает и наезжает на соседнее, поэтому крупные
 *  величины подписываются сокращённо — точные значения читаются в подсказке. */
const compactAxisNumber = new Intl.NumberFormat("ru-RU", { notation: "compact", maximumFractionDigits: 1 });
export function axisNumber(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  return Math.abs(value) < 10_000 ? value.toLocaleString("ru-RU") : compactAxisNumber.format(value);
}

/** Русское согласование с числом: 1 канал, 2 канала, 5 каналов. */
export function plural(value: number, one: string, few: string, many: string) {
  const mod100 = Math.abs(value) % 100;
  const mod10 = mod100 % 10;
  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}
