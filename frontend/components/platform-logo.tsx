import type { Platform } from "@/lib/types";
import { PLATFORM_LONG_LABELS } from "@/lib/format";
import { cn } from "@/lib/utils";

type Network = Exclude<Platform, "all">;

/** Официальные знаки площадок (public/brands, источники — в SOURCES.md).
 *  Новая площадка — одна строка здесь и файл рядом с остальными. */
const LOGOS: Record<Network, string> = {
  telegram: "/brands/telegram.svg",
  vk: "/brands/vk.svg",
  max: "/brands/max.svg",
  rutube: "/brands/rutube.svg",
};

export function PlatformLogo({ platform, size = 40, className, decorative = false }: {
  platform: Network; size?: number; className?: string; decorative?: boolean;
}) {
  return (
    // Знаки не перерисовываются и не перекрашиваются: это файлы из брендбуков.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={LOGOS[platform]} width={size} height={size} loading="lazy" decoding="async"
      alt={decorative ? "" : PLATFORM_LONG_LABELS[platform]} className={cn("shrink-0", className)} />
  );
}
