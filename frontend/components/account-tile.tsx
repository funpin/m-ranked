import type { ReactNode } from "react";
import { DeltaBadge, type DeltaTone } from "@/components/delta-badge";
import { SummaryTile } from "@/components/summary-tile";

/** Плитка сводки аккаунта с плашкой изменения за сутки. */
export function Tile({ value, label, icon, note, delta, tone, deltaLabel, footer }: {
  value: string; label: string; icon: ReactNode; note?: string;
  delta?: number | null; tone?: DeltaTone; deltaLabel?: string; footer?: ReactNode;
}) {
  return (
    <SummaryTile value={value} label={label} icon={icon} note={note} footer={footer}
      trailing={<DeltaBadge value={delta} tone={tone} label={deltaLabel ?? label} />} />
  );
}

/** Разница, когда обе величины известны. Иначе сравнивать не с чем. */
export function change(current: number | null | undefined,
                       previous: number | null | undefined): number | null {
  if (current === null || current === undefined) return null;
  if (previous === null || previous === undefined) return null;
  return current - previous;
}
