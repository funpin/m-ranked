import { StatusPill } from "@/components/ui";
import { LevelIcon } from "@/components/anomaly-level-icon";
import { PromotionMark } from "@/components/findings/account-findings-flag";
import type { AccountLevelsLoad } from "@/lib/anomaly";
import { cn } from "@/lib/utils";

/** Уровень поста по загруженной карте уровней аккаунта. Пометка продвижения
 *  (ВК) стоит рядом с уровнем, как в «Находках»: это контекст, а не уровень. */
export function LevelBadge({ loaded, publicationId }: { loaded: AccountLevelsLoad; publicationId: string | null }) {
  if (!loaded) return <span className="text-muted-foreground" title="Результат анализа временно недоступен">—</span>;
  const item = publicationId ? loaded.get(publicationId) : undefined;
  if (!item) return <span className="text-muted-foreground inline-flex items-center gap-1.5 whitespace-nowrap" title="Пост ещё не проанализирован"><LevelIcon level={null} className="size-3.5" />ожидает</span>;
  const level = item.level === 0
    ? <span className="text-muted-foreground inline-flex items-center gap-1.5 whitespace-nowrap"><LevelIcon level={item.levelSymbol === "·" ? null : 0} className="size-3.5" />{item.levelLabel}</span>
    : <span className="inline-flex whitespace-nowrap">
        <StatusPill tone={item.level === 1 ? "neutral" : item.level === 3 ? "red" : "amber"}>
          <LevelIcon level={item.level} className={cn("size-3.5", item.level === 1 && "text-chart-3")} />{item.levelLabel}
        </StatusPill>
      </span>;
  if (!item.promotion) return level;
  return <span className="inline-flex items-center gap-2 whitespace-nowrap">{level}<PromotionMark promoted /></span>;
}
