import { Suspense } from "react";
import { TableCell } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui";
import { LevelIcon } from "@/components/anomaly-icons";
import type { AccountLevelsLoad } from "@/lib/anomaly";
import { cn } from "@/lib/utils";

/** Ячейка уровня в таблице публикаций аккаунта. Таблица её не ждёт: пока
 *  ответ анализа в пути, на месте уровня скелетон. */
export function AnomalyLevelCell({ levels, publicationId }: {
  levels: Promise<AccountLevelsLoad>; publicationId: string | null;
}) {
  return (
    <TableCell data-testid="anomaly-level-cell">
      <Suspense fallback={<Skeleton className="h-5 w-24" aria-label="Уровень анализа загружается" />}>
        <Level levels={levels} publicationId={publicationId} />
      </Suspense>
    </TableCell>
  );
}

async function Level({ levels, publicationId }: { levels: Promise<AccountLevelsLoad>; publicationId: string | null }) {
  const loaded = await levels;
  if (!loaded) return <span className="text-muted-foreground" title="Результат анализа временно недоступен">—</span>;
  const item = publicationId ? loaded.get(publicationId) : undefined;
  if (!item) return <span className="text-muted-foreground inline-flex items-center gap-1.5 whitespace-nowrap" title="Пост ещё не проанализирован"><LevelIcon level={null} className="size-3.5" />ожидает</span>;
  if (item.level === 0) {
    return <span className="text-muted-foreground inline-flex items-center gap-1.5 whitespace-nowrap"><LevelIcon level={0} className="size-3.5" />нет аномалий</span>;
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
