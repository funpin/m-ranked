import { Icon } from "@/components/icon-sprite";
import { cn } from "@/lib/utils";

/** Как читать знак: обычно рост хорош, а для места в рейтинге — наоборот. */
export type DeltaTone = "growth" | "rank";

function sign(value: number) {
  return value > 0 ? "+" : value < 0 ? "−" : "";
}

function short(value: number) {
  const size = Math.abs(value);
  if (size >= 1_000_000) return `${Math.round(size / 100_000) / 10} млн`;
  if (size >= 10_000) return `${Math.round(size / 1000)} тыс.`;
  return new Intl.NumberFormat("ru-RU").format(size);
}

/**
 * Плашка изменения рядом с числом.
 *
 * Показывается только когда сравнивать есть с чем: пустая рамка на месте
 * несуществующего сравнения врёт не меньше, чем нарисованный ноль. За месяц
 * истории наблюдений пока не хватает, и там плашки просто нет.
 *
 * У места в рейтинге знак читается наоборот: подняться — это уменьшить номер,
 * поэтому −3 показывается зелёным и со стрелкой вверх.
 */
export function DeltaBadge({ value, tone = "growth", label, className }: {
  value: number | null | undefined;
  tone?: DeltaTone;
  label?: string;
  className?: string;
}) {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  const better = tone === "rank" ? value < 0 : value > 0;
  const worse = tone === "rank" ? value > 0 : value < 0;
  // У места в рейтинге печатается не разность номеров, а насколько поднялись:
  // подняться на 63 позиции — это уменьшить номер на 63, и «−63» рядом с
  // зелёной стрелкой вверх читалось как падение. Цвет и стрелка были правы,
  // врал только знак у числа.
  const shown = tone === "rank" ? -value : value;
  const name = value === 0 ? "minus" : better ? "trending-up" : "trending-down";
  const words = value === 0 ? "без изменений" : `${better ? "рост" : "спад"} на ${short(value)}`;
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-semibold tabular",
        better && "bg-success/12 text-success",
        worse && "bg-destructive/12 text-destructive",
        value === 0 && "bg-muted text-muted-foreground",
        className,
      )}
      title={label ? `${label}: ${words}` : words}
    >
      <Icon name={name} className="size-3 shrink-0" />
      {value === 0 ? "0" : `${sign(shown)}${short(shown)}`}
    </span>
  );
}
