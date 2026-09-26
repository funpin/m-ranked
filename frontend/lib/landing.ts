/** Главная страница: геометрия иллюстраций, числа сводки, выжимка панели
 *  сравнения. Здесь только чистые функции — их проверяют модульные тесты,
 *  а компоненты главной лишь рисуют результат. */
import type { components } from "../../contracts/openapi/m-ranked-v1-client";
import type { Dashboard } from "./compare-dashboard";
import { plural } from "./format";

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

/** Только то, что рисуют графики главной: сутки по площадкам, ритм
 *  публикаций и итоги анализа по площадкам. Кривые, типы и строки вузов в
 *  разметку главной не попадают — это десятки килобайт, которых никто не увидит. */
export function landingDashboard(data: Dashboard): Dashboard {
  return {
    ...data,
    institutions: [],
    stats: data.stats.filter((stat) => stat.institutionId === null),
    curves: [],
    types: [],
  };
}

// --- Геометрия иллюстраций ---

const round = (value: number) => Math.round(value * 10) / 10;
const hundredths = (value: number) => Math.round(value * 100) / 100;

export type ScenePoint = readonly [number, number, number];
export interface SceneCurve { points: ScenePoint[]; tone: number; lead: boolean; delay: number }


/** Трёхмерная модель первого экрана — «рельеф замеров». Каждая кривая —
 *  пост: по оси x его возраст, по y накопленные просмотры, по z — место в
 *  ленте. Пост стартует в свой момент, быстро растёт и выходит на плато;
 *  точки гуще в начале, как в настоящем расписании сбора. Кривых немного:
 *  модель передаёт идею, а не изображает данные. Координаты — в
 *  единицах сцены: x ∈ [-3.2; 3.2], y ∈ [0; 2.4], z ∈ [-2.2; 2.2]. */
export function sceneCurves({ samples = 40 } = {}): SceneCurve[] {
  // Четыре площадки — четыре ведущие кривые разной высоты и крутизны; рядом
  // с каждой — тихая кривая другого поста того же аккаунта.
  const leads = [
    { z: -1.8, start: -3.0, amplitude: 1.55, tau: 0.55, delay: 0 },
    { z: -0.6, start: -2.7, amplitude: 2.15, tau: 0.8, delay: 0.25 },
    { z: 0.6, start: -2.3, amplitude: 1.25, tau: 0.42, delay: 0.5 },
    { z: 1.8, start: -2.85, amplitude: 1.8, tau: 0.95, delay: 0.75 },
  ];
  const curves: SceneCurve[] = [];
  for (const [tone, lead] of leads.entries()) {
    for (const quiet of [false, true]) {
      const start = lead.start + (quiet ? 0.9 : 0);
      const amplitude = lead.amplitude * (quiet ? 0.5 : 1);
      const points: ScenePoint[] = [];
      for (let step = 0; step < samples; step += 1) {
        const x = start + (3.2 - start) * (step / (samples - 1)) ** 1.6;
        points.push([hundredths(x), hundredths(amplitude * (1 - Math.exp(-(x - start) / lead.tau))), hundredths(lead.z + (quiet ? 0.38 : 0))]);
      }
      curves.push({ points, tone, lead: !quiet, delay: lead.delay + (quiet ? 0.4 : 0) });
    }
  }
  return curves;
}

/** Схема автоматического анализа: обычный разброс площадки, живые посты
 *  внутри него и формы, которые анализатор отмечает. У всех кривых одинаковое
 *  число точек, чтобы переход между ними анимировался плавно. Координаты — в
 *  поле 640 × 300. */
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

/** Живой пост: скорость роста неровная — всплески, паузы, суточный ритм, —
 *  но счётчик не убывает. Считается как сумма шагов с «шумной» скоростью. */
function live(t: number, seed: number, scale = 1) {
  const steps = 80;
  let value = 0;
  for (let step = 0; step < Math.round(t * steps); step += 1) {
    const at = (step + 0.5) / steps;
    const rate = 0.52 * 5.2 * Math.exp(-at * 5.2) / steps;
    // В первые минуты шум мал: рост ещё не успел разойтись.
    const noise = Math.min(1, at * 5) * (0.75 * Math.sin(at * 23 + seed) + 0.45 * Math.sin(at * 61 + seed * 2.3));
    value += rate * Math.max(0, 1 + noise);
  }
  // Живой пост остаётся внутри обычного разброса; границы монотонны, поэтому
  // и ограниченный ряд не убывает.
  const expected = typical(t);
  return Math.min(expected * 1.28, Math.max(expected * 0.74, value * scale));
}

function polyline(values: (t: number) => number) {
  const parts: string[] = [];
  for (let index = 0; index < CORRIDOR_POINTS; index += 1) {
    const t = index / (CORRIDOR_POINTS - 1);
    parts.push(`${index ? "L" : "M"}${round(corridorX(t))} ${round(corridorY(values(t)))}`);
  }
  return parts.join("");
}

/** Обычный разброс площадки: между «тихими» и «громкими» постами того же возраста. */
export function corridorBand() {
  const upper: string[] = [];
  const lower: string[] = [];
  for (let index = 0; index < CORRIDOR_POINTS; index += 1) {
    const t = index / (CORRIDOR_POINTS - 1);
    upper.push(`${round(corridorX(t))} ${round(corridorY(typical(t) * 1.34))}`);
    lower.unshift(`${round(corridorX(t))} ${round(corridorY(typical(t) * 0.68))}`);
  }
  // Подпись встаёт над верхней границей у правого края.
  return { area: `M${upper.join("L")}L${lower.join("L")}Z`, median: polyline(typical), labelY: round(corridorY(typical(1) * 1.34) - 10) };
}

/** Несколько обычных постов: все разные и неровные, но в пределах разброса. */
export function corridorCrowd() {
  return [[0.7, 0.86], [1.9, 1.12], [3.1, 0.94], [4.4, 1.22], [5.6, 0.78]].map(([seed, scale]) => polyline((t) => live(t, seed!, scale!)));
}

export const CORRIDOR_SHAPES = [
  {
    id: "normal", title: "Живой рост", level: 0,
    text: "Рост неровный: всплески, паузы, суточный ритм. Пока кривая в пределах обычного разброса площадки, это шум, а не сигнал.",
    values: (t: number) => live(t, 0.3, 1.04),
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
  { level: 0, title: "Нет признаков", text: "Рост в пределах обычного разброса площадки." },
  { level: 1, title: "Уровень 1", text: "Один признак средней силы или несколько слабых." },
  { level: 2, title: "Уровень 2", text: "Один сильный признак." },
  { level: 3, title: "Признаки искусственной активности", text: "Сильные признаки из двух разных семейств сразу." },
] as const;
