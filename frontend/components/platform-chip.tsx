import { PLATFORM_LABELS } from "@/lib/format";
import type { Platform } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Each platform keeps a distinct, stable colour so a mixed list can be
 *  scanned by platform without reading every label. */
// Stroke colours stay in the background tint; small text needs a darker ramp.
const TONES: Record<Platform, string> = {
  all: "bg-muted text-muted-foreground",
  telegram: "bg-chart-2/12 text-blue-800 dark:text-blue-300",
  vk: "bg-chart-9/12 text-sky-800 dark:text-sky-300",
  max: "bg-chart-4/12 text-purple-800 dark:text-purple-300",
  rutube: "bg-chart-8/12 text-pink-800 dark:text-pink-300",
};

export function PlatformChip({ platform, label, className }: {
  platform: Platform;
  label?: string;
  className?: string;
}) {
  return (
    <span className={cn("inline-block min-w-[66px] rounded-md px-1.5 py-0.5 text-center text-[11px] font-black", TONES[platform], className)}>
      {label ?? PLATFORM_LABELS[platform]}
    </span>
  );
}
