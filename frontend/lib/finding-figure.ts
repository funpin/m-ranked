import type { AccountAnomalyFinding } from "@/lib/types";

export type Figure = NonNullable<AccountAnomalyFinding["figure"]>;

// Ниже этого «разброс сверх случайного» показывается как 0,00: делить на него —
// получать бессмысленные «в 291 раз».
const ZERO = 0.005;

/** «в 6,8 раза выше» — во сколько раз аккаунт отличается от типичного в сторону находки. */
export function figureComparison(figure: Figure): string | null {
  const { value, typical, unit } = figure;
  if (unit === "percent") return value - typical >= 0.05 ? `+${Math.round((value - typical) * 100)} п. п.` : null;
  if (figure.direction === "lower" && value < ZERO) return unit === "decimal" ? "не больше случайного" : "около нуля";
  const ratio = figure.direction === "lower" ? typical / value : value / Math.max(typical, 1e-3);
  if (!Number.isFinite(ratio) || ratio < 1.5) return null;
  const whole = Math.round(ratio);
  const text = ratio < 10 ? ratio.toFixed(1).replace(".", ",") : String(whole);
  // «в 2,5 раза», «в 23 раза», «в 15 раз»
  const word = ratio < 10 || (whole % 10 >= 2 && whole % 10 <= 4 && (whole % 100 < 12 || whole % 100 > 14)) ? "раза" : "раз";
  return `в ${text} ${word} ${figure.direction === "lower" ? "ниже" : "выше"}`;
}
