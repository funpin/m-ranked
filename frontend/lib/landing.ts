/** Главная страница: геометрия иллюстраций, числа сводки, выжимка панели
 *  сравнения. Здесь только чистые функции — их проверяют модульные тесты,
 *  а компоненты главной лишь рисуют результат. */
import type { components } from "../../contracts/openapi/m-ranked-v1-client";
import type { Dashboard } from "./compare-dashboard";

export type SiteSummary = components["schemas"]["SiteSummary"];

/** Площадки, которые главная знает по имени, и их публичные счётчики
 *  (docs/MULTIPLATFORM.md). Новая площадка из сводки всё равно появится —
 *  с общим цветом и без списка счётчиков. */
export const KNOWN_PLATFORMS = {
  telegram: { name: "Telegram", unit: "канал", metrics: ["просмотры", "реакции по типам", "комментарии", "пересылки"] },
  vk: { name: "ВКонтакте", unit: "сообщество", metrics: ["просмотры", "лайки", "комментарии", "репосты"] },
  max: { name: "MAX", unit: "канал", metrics: ["просмотры", "реакции по типам", "комментарии"] },
  rutube: { name: "Rutube", unit: "канал", metrics: ["просмотры", "лайки", "комментарии"] },
} as const;
export type KnownPlatform = keyof typeof KNOWN_PLATFORMS;

export function isKnownPlatform(value: string): value is KnownPlatform {
  return Object.hasOwn(KNOWN_PLATFORMS, value);
}

/** Площадки сводки в порядке убывания числа аккаунтов, при равенстве — по
 *  имени: порядок не прыгает между пересчётами. */
export function platformsFromSummary(summary: Pick<SiteSummary, "accountsByPlatform">) {
  return Object.entries(summary.accountsByPlatform ?? {})
    .filter(([, count]) => count > 0)
    .sort(([a, left], [b, right]) => right - left || a.localeCompare(b))
    .map(([platform, accounts]) => ({ platform, accounts }));
}

const integer = new Intl.NumberFormat("ru-RU");
const oneDecimal = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });

/** Крупное число для витрины: до миллиона — полностью, дальше — «13,2 млн». */
export function formatStat(value: number) {
  if (Math.abs(value) >= 1_000_000_000) return `${oneDecimal.format(value / 1_000_000_000)} млрд`;
  if (Math.abs(value) >= 1_000_000) return `${oneDecimal.format(value / 1_000_000)} млн`;
  return integer.format(Math.round(value));
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

const UNIT_FORMS: Record<string, [string, string, string]> = {
  канал: ["канал", "канала", "каналов"],
  сообщество: ["сообщество", "сообщества", "сообществ"],
  аккаунт: ["аккаунт", "аккаунта", "аккаунтов"],
};
export function countWithUnit(value: number, unit: string) {
  const forms = UNIT_FORMS[unit] ?? UNIT_FORMS.аккаунт!;
  return `${integer.format(value)} ${plural(value, ...forms)}`;
}

/** Дата пересчёта сводки: «26 сентября 2026». */
export function summaryDate(iso: string) {
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Moscow" })
    .format(new Date(iso)).replace(/\s*г\.$/, "");
}

/** Расписание замеров: чем моложе пост, тем чаще. Совпадает с настройками
 *  сборщиков на проде; через 30 суток сбор по посту завершается. */
export const COLLECTION_SCHEDULE = [
  { age: "первые сутки", step: "5 мин", share: 1 },
  { age: "2–3 сутки", step: "15 мин", share: 2 },
  { age: "4–6 сутки", step: "30 мин", share: 3 },
  { age: "7–30 сутки", step: "60 мин", share: 24 },
] as const;
export const RUTUBE_SCHEDULE = "от часа в первые трое суток до 12 часов к концу месяца";
export const TRACKING_DAYS = 30;

/** Только то, что рисуют графики главной: сутки по площадкам и кривые
 *  просмотров. Остальное (тепловая карта, типы, реакции, счётчики по вузам) в разметку
 *  главной не попадает — это десятки килобайт, которых никто не увидит. */
export function landingDashboard(data: Dashboard): Dashboard {
  return {
    ...data,
    stats: data.stats.filter((stat) => stat.institutionId === null),
    curves: data.curves.map((curve) => ({ ...curve, reactions: [] })),
    timing: [],
    types: [],
  };
}

// --- Геометрия иллюстраций ---

/** Детерминированный генератор (mulberry32): сервер и клиент получают одну
 *  и ту же картинку, и она не меняется от сборки к сборке. */
export function seeded(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const round = (value: number) => Math.round(value * 10) / 10;
const hundredths = (value: number) => Math.round(value * 100) / 100;

export type ScenePoint = readonly [number, number, number];
export interface SceneCurve { points: ScenePoint[]; tone: number; lead: boolean; delay: number }

/** Трёхмерная модель первого экрана — «рельеф замеров». Каждая кривая —
 *  пост: по оси x его возраст, по y накопленные просмотры, по z — место в
 *  ленте. Пост стартует в свой момент, быстро растёт и выходит на плато;
 *  точки гуще в начале, как в настоящем расписании сбора. Координаты — в
 *  единицах сцены: x ∈ [-3.2; 3.2], y ∈ [0; 2.4], z ∈ [-2.2; 2.2]. */
export function sceneCurves({ count = 26, samples = 48, seed = 20260926 } = {}): SceneCurve[] {
  const random = seeded(seed);
  const curves: SceneCurve[] = [];
  for (let index = 0; index < count; index += 1) {
    const z = -2.2 + (4.4 * index) / Math.max(1, count - 1) + (random() - 0.5) * 0.08;
    const start = -3.2 + random() * 1.8;
    // Разброс охвата огромный: немногие посты набирают в разы больше прочих.
    const amplitude = 0.3 + 2.1 * random() ** 1.8;
    const tau = 0.25 + random() * 1.1;
    const points: ScenePoint[] = [];
    for (let step = 0; step < samples; step += 1) {
      const x = start + (3.2 - start) * (step / (samples - 1)) ** 1.6;
      points.push([hundredths(x), hundredths(amplitude * (1 - Math.exp(-(x - start) / tau))), hundredths(z)]);
    }
    curves.push({ points, tone: index % 4, lead: index % 7 === 3, delay: round(random() * 12) / 10 });
  }
  return curves;
}

/** Схема «коридора нормы»: одинаковое число точек у всех кривых, чтобы
 *  переход между ними анимировался плавно. Координаты — в поле 640 × 300. */
export const CORRIDOR = { width: 640, height: 300, left: 36, right: 620, top: 24, bottom: 268 } as const;
const CORRIDOR_POINTS = 41;

function corridorX(t: number) {
  return CORRIDOR.left + (CORRIDOR.right - CORRIDOR.left) * t;
}
function corridorY(value: number) {
  return CORRIDOR.bottom - (CORRIDOR.bottom - CORRIDOR.top) * value;
}
/** Типичный рост поста в долях от верха поля. */
function typical(t: number) {
  return 0.52 * (1 - Math.exp(-t * 5.2));
}

function polyline(values: (t: number) => number) {
  const parts: string[] = [];
  for (let index = 0; index < CORRIDOR_POINTS; index += 1) {
    const t = index / (CORRIDOR_POINTS - 1);
    parts.push(`${index ? "L" : "M"}${round(corridorX(t))} ${round(corridorY(values(t)))}`);
  }
  return parts.join("");
}

/** Коридор нормы площадки: между «тихими» и «громкими» постами того же возраста. */
export function corridorBand() {
  const upper: string[] = [];
  const lower: string[] = [];
  for (let index = 0; index < CORRIDOR_POINTS; index += 1) {
    const t = index / (CORRIDOR_POINTS - 1);
    upper.push(`${round(corridorX(t))} ${round(corridorY(typical(t) * 1.34))}`);
    lower.unshift(`${round(corridorX(t))} ${round(corridorY(typical(t) * 0.68))}`);
  }
  // Подпись встаёт над верхней границей коридора у правого края.
  return { area: `M${upper.join("L")}L${lower.join("L")}Z`, median: polyline(typical), labelY: round(corridorY(typical(1) * 1.34) - 10) };
}

export const CORRIDOR_SHAPES = [
  {
    id: "normal", title: "Обычный пост", level: 0,
    text: "Быстрый старт, затем плавное замедление. Кривая остаётся в коридоре своей площадки.",
    values: (t: number) => typical(t) * 1.06 + 0.012 * Math.sin(t * 9),
  },
  {
    id: "linear", title: "Линейная подача", level: 1,
    text: "Просмотры прибывают ровно, с одной скоростью, и не замедляются, как у живой аудитории.",
    values: (t: number) => Math.min(0.9, 0.05 + t * 0.86),
  },
  {
    id: "late", title: "Поздний скачок", level: 2,
    text: "Пост уже затих, и вдруг — резкий прирост, которого нет у соседних постов аккаунта.",
    values: (t: number) => typical(t) * 1.02 + (t > 0.58 ? 0.36 * (1 - Math.exp(-(t - 0.58) * 26)) : 0),
  },
  {
    id: "plateau", title: "Рывок в плато", level: 2,
    text: "Почти весь охват приходит за минуты, после чего счётчик замирает.",
    values: (t: number) => (t < 0.12 ? typical(t) * 0.8 : 0.2 + 0.64 * (1 - Math.exp(-(t - 0.12) * 60))),
  },
] as const;
export type CorridorShapeId = (typeof CORRIDOR_SHAPES)[number]["id"];

export function corridorShapePath(id: CorridorShapeId) {
  return polyline(CORRIDOR_SHAPES.find((shape) => shape.id === id)!.values);
}

/** Уровни анализа — как в самом анализаторе (anomaly_analysis/v2/levels.py). */
export const ANALYSIS_LEVELS = [
  { level: 0, title: "Нет признаков", text: "Рост в пределах нормы площадки." },
  { level: 1, title: "Уровень 1", text: "Один признак средней силы или несколько слабых." },
  { level: 2, title: "Уровень 2", text: "Один сильный признак." },
  { level: 3, title: "Признаки искусственной активности", text: "Сильные признаки из двух разных семейств сразу." },
] as const;
