import type { LucideIcon } from "lucide-react";
import { PlatformLogo } from "@/components/platform-logo";
import { cn } from "@/lib/utils";

export type RatingPlatform = "telegram" | "vk" | "max" | "rutube";

const NAMES: Record<RatingPlatform, string> = { telegram: "Telegram", vk: "VK", max: "MAX", rutube: "Rutube" };
const FILL: Record<RatingPlatform, string> = {
  telegram: "bg-platform-telegram", vk: "bg-platform-vk", max: "bg-platform-max", rutube: "bg-platform-rutube",
};

/** Формула картинкой: полоса делится между площадками по весам. Площадка с весом 0
 *  остаётся в конце штриховкой — видно, что её нет в формуле. */
export function WeightStrip({ weights, label }: { weights: Partial<Record<RatingPlatform, number>>; label: string }) {
  const order: RatingPlatform[] = ["telegram", "vk", "max", "rutube"];
  const counted = order.filter((key) => (weights[key] ?? 0) > 0).sort((a, b) => (weights[b] ?? 0) - (weights[a] ?? 0));
  const absent = order.filter((key) => !((weights[key] ?? 0) > 0));
  const total = counted.reduce((sum, key) => sum + (weights[key] ?? 0), 0);
  return <figure data-testid="weight-strip">
    <figcaption className="sr-only">{label}: {counted.map((key) => `${NAMES[key]} ${Math.round(100 * (weights[key] ?? 0))} %`).join(", ")}
      {absent.length ? `; не учитывается: ${absent.map((key) => NAMES[key]).join(", ")}` : ""}</figcaption>
    <div aria-hidden="true" className="flex h-11 w-full gap-1">
      {counted.map((key) => <div key={key} style={{ flexGrow: weights[key] }}
        className={cn("flex min-w-0 basis-0 items-center gap-1.5 rounded-md px-1.5 sm:gap-2 sm:px-2 text-white dark:text-neutral-950", FILL[key])}>
        <span className="rounded-sm bg-white p-0.5"><PlatformLogo platform={key} size={18} decorative /></span>
        <span className="hidden truncate text-sm font-semibold sm:inline">{NAMES[key]}</span>
        <span className="ml-auto text-sm font-semibold whitespace-nowrap tabular-nums">{Math.round((100 * (weights[key] ?? 0)) / total)} %</span>
      </div>)}
      {absent.map((key) => <div key={key} title={`${NAMES[key]} не учитывается`}
        className="text-muted-foreground flex basis-11 items-center justify-center gap-1.5 rounded-md border border-dashed px-2 text-xs line-through sm:basis-28">
        <PlatformLogo platform={key} size={16} decorative className="opacity-50 grayscale" /><span className="hidden sm:inline">{NAMES[key]}</span>
      </div>)}
    </div>
  </figure>;
}

/** Часть балла или правило: значок и 2–5 слов; подробность — во второй строке. */
export function Glyphs({ items, tone = "neutral" }: {
  items: { icon: LucideIcon; label: string; detail?: string }[]; tone?: "neutral" | "minus";
}) {
  return <ul className="grid gap-x-4 gap-y-3 sm:grid-cols-3">
    {items.map(({ icon: Icon, label, detail }) => <li key={label} className="flex items-start gap-2.5">
      <span className={cn("grid size-8 shrink-0 place-items-center rounded-full",
        tone === "minus" ? "bg-destructive/10 text-destructive" : "bg-background text-foreground ring-border ring-1")}>
        <Icon className="size-4" aria-hidden="true" />
      </span>
      <span className="leading-tight">
        <span className="block text-sm font-medium">{label}</span>
        {detail ? <span className="text-muted-foreground block text-xs">{detail}</span> : null}
      </span>
    </li>)}
  </ul>;
}

/** Балл 0–100 полоской цвета площадки; число рядом. Без балла — прочерк. */
export function ScoreBar({ value, platform, ghost, title }: {
  value: number | null; platform?: RatingPlatform; ghost?: number | null; title?: string;
}) {
  if (value === null) return <span className="text-muted-foreground" title={title}>—</span>;
  return <span className="inline-flex w-full min-w-20 items-center gap-2" title={title}>
    <span aria-hidden="true" className="bg-muted relative h-2 flex-1 overflow-hidden rounded-full">
      {ghost !== undefined && ghost !== null && ghost > value
        ? <span className={cn("absolute inset-y-0 left-0 rounded-full opacity-25", platform ? FILL[platform] : "bg-chart-1")}
          style={{ width: `${Math.min(100, ghost)}%` }} /> : null}
      <span className={cn("absolute inset-y-0 left-0 rounded-full", platform ? FILL[platform] : "bg-chart-1")}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </span>
    <span className="w-7 text-right tabular-nums">{value.toFixed(0)}</span>
  </span>;
}
