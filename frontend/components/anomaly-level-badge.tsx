import { StatusPill } from "@/components/ui";
import { LevelIcon } from "@/components/anomaly-icons";
import type { AccountLevelsLoad } from "@/lib/anomaly";
import { cn } from "@/lib/utils";

/** Уровень поста по загруженной карте уровней аккаунта. */
export function LevelBadge({ loaded, publicationId }: { loaded: AccountLevelsLoad; publicationId: string | null }) {
  if (!loaded) return <span className="text-muted-foreground" title="Результат анализа временно недоступен">—</span>;
  const item = publicationId ? loaded.get(publicationId) : undefined;
  if (!item) return <span className="text-muted-foreground inline-flex items-center gap-1.5 whitespace-nowrap" title="Пост ещё не проанализирован"><LevelIcon level={null} className="size-3.5" />ожидает</span>;
  if (item.level === 0) {
    return <span className="text-muted-foreground inline-flex items-center gap-1.5 whitespace-nowrap"><LevelIcon level={item.levelSymbol === "·" ? null : 0} className="size-3.5" />{item.levelLabel}</span>;
  }
  const tone = item.level === 3 ? "red" : "amber";
  return (
    <span className="inline-flex whitespace-nowrap">
      <StatusPill tone={item.level === 1 ? "neutral" : tone}>
        <LevelIcon level={item.level} className={cn("size-3.5", item.level === 1 && "text-chart-3")} />{item.levelLabel}
      </StatusPill>
    </span>
  );
}
