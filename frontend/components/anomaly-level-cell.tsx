import { Suspense } from "react";
import { TableCell } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { LevelBadge } from "@/components/anomaly-level-badge";
import type { AccountLevelsLoad } from "@/lib/anomaly";

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
  return <LevelBadge loaded={await levels} publicationId={publicationId} />;
}
