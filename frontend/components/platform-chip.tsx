import { PLATFORM_LABELS } from "@/lib/format";
import type { Platform } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Each platform keeps a distinct, stable colour so a mixed list can be
 *  scanned by platform without reading every label. */
const TONES: Record<Platform, string> = {
  all: "bg-muted text-muted-foreground",
  telegram: "bg-chart-2/12 text-chart-2",
  vk: "bg-chart-9/12 text-chart-9",
  max: "bg-chart-4/12 text-chart-4",
  rutube: "bg-chart-8/12 text-chart-8",
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
