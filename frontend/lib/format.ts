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

export function legacyDate(value: string | null | undefined, withZone = false): string {
  if (!value) return "—";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Moscow", day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false }).formatToParts(date);
  const get = (name: string) => parts.find((part) => part.type === name)?.value;
  return `${get("day")}.${get("month")}.${get("year")}, ${get("hour")}:${get("minute")}:${get("second")}${withZone ? " МСК" : ""}`;
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
  if (platform === "telegram") return `№${externalId}`;
  if (platform === "vk" && /^-?\d+_\d+$/.test(externalId)) return `№${externalId.split("_").at(-1)}`;
  return externalId;
}
export function postTypeLabel(value: string) { return ({text:"текст",photo:"фото",video:"видео",album:"альбом",document:"документ",poll:"опрос",webpage:"веб-страница",contact:"контакт",geo:"геолокация",media:"медиа"} as Record<string,string>)[value] ?? value; }
