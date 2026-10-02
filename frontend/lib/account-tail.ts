import type { AccountTailProfile } from "./types";

/** Профиль позднего отклика; null — ответ анализа не пришёл. */
export type TailProfileLoad = AccountTailProfile | null;

/** Реакций на сто просмотров: меньше единицы — два знака, иначе один. */
const percent = (value: number) => (value * 100).toFixed(value * 100 < 1 ? 2 : 1).replace(".", ",");
const times = (value: number | null) => value === null ? "—"
  : `${value < 10 ? value.toFixed(2).replace(".", ",") : Math.round(value)}×`;
const shortDate = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", timeZone: "UTC" });
const count = (value: number) => value.toLocaleString("ru-RU");

/** Слова и числа блока. Формулировки — о статистике, без выводов о намерениях. */
export function tailSummary(profile: AccountTailProfile) {
  const metrics = profile.metrics;
  const label = profile.status === "pending" ? "ещё не рассчитан" : profile.levelLabel;
  if (!metrics) return { level: profile.level, label, metrics: null } as const;
  const cohort = metrics.cohort;
  const window = `${shortDate.format(new Date(metrics.windowStart))} — ${shortDate.format(new Date(metrics.windowEnd))}`;
  const median = cohort ? cohort.median : null;
  const sentence = metrics.posts
    ? `На ${metrics.posts} постах поздние просмотры (+${count(metrics.lateViews)}) принесли +${count(metrics.lateReactions)} реакций; `
      + `в первые сутки те же посты собрали ${count(metrics.earlyReactions)} реакций на ${count(metrics.earlyViews)} просмотров. `
      + (median !== null
        ? `Поздняя доля составляет ${times(metrics.ratio)} ранней; у типичного аккаунта площадки — ${times(median)}.`
        : `Поздняя доля составляет ${times(metrics.ratio)} ранней.`)
      + (metrics.activeDays ? ` Поздние реакции сразу на нескольких постах были в ${metrics.activeDays} сутках из ${metrics.days.length}.` : "")
      + (metrics.roundedPosts ? " Счётчики площадки округлены, поэтому доли приблизительные; сравнение идёт только с аккаунтами той же площадки." : "")
    : "Нет постов с точными замерами в первые сутки и после четырёх суток.";
  return {
    level: profile.level, label, metrics, window, sentence,
    abstainText: metrics.abstainText ?? null,
    earlyRate: percent(metrics.earlyRate), lateRate: percent(metrics.lateRate), ratio: times(metrics.ratio),
    cohortText: cohort && cohort.rank !== undefined
      ? `поздняя доля к ранней · выше, чем у ${Math.round(cohort.rank * 100)} % аккаунтов` : null,
  } as const;
}
