"use client";

import { useMemo } from "react";
import { WEEKDAYS, formatInteger, timingGrid, type Dashboard, type DashboardPlatform } from "@/lib/compare-dashboard";

/** Тепловая карта «день недели × час выхода»: число публикаций, в подсказке —
 *  медиана просмотров за сутки. Сетка из блоков, без графической библиотеки. */
export function TimingHeatmap({ data, platform }: { data: Dashboard; platform: DashboardPlatform }) {
  const grid = useMemo(() => timingGrid(data, platform), [data, platform]);
  const peak = Math.max(1, ...grid.flat().map((cell) => cell.posts));
  return (
    // На узком экране сетка прокручивается: область фокусируется с клавиатуры.
    <div className="overflow-x-auto focus-visible:ring-ring/50 rounded-md focus-visible:ring-[3px] focus-visible:outline-none"
      data-testid="timing-heatmap" tabIndex={0} role="region" aria-label="Публикации по дню недели и часу выхода">
      <div className="grid min-w-[560px] gap-[3px]" style={{ gridTemplateColumns: "28px repeat(24, minmax(0, 1fr))" }} role="table" aria-label="Публикации по дню недели и часу">
        <span />
        {Array.from({ length: 24 }, (_, hour) => (
          <span key={hour} className="text-muted-foreground text-center text-[10px]">{hour % 3 === 0 ? hour : ""}</span>
        ))}
        {grid.map((row, weekday) => (
          <div key={weekday} className="contents" role="row">
            <span className="text-muted-foreground self-center text-[11px]" role="rowheader">{WEEKDAYS[weekday]}</span>
            {row.map((cell, hour) => {
              const intensity = cell.posts / peak;
              return (
                <span key={hour} role="cell"
                  title={`${WEEKDAYS[weekday]}, ${String(hour).padStart(2, "0")}:00 — ${formatInteger(cell.posts)} публ., медиана просмотров за 24 ч: ${formatInteger(cell.views24)}`}
                  className="aspect-square rounded-[3px]"
                  style={{ background: cell.posts ? `color-mix(in oklch, var(--chart-2) ${Math.round(12 + intensity * 88)}%, transparent)` : "var(--muted)" }} />
              );
            })}
          </div>
        ))}
      </div>
      <div className="text-muted-foreground mt-2 flex items-center gap-2 text-[11px]">
        меньше
        {[0.12, 0.35, 0.6, 0.85, 1].map((step) => (
          <span key={step} className="size-3 rounded-[3px]" style={{ background: `color-mix(in oklch, var(--chart-2) ${Math.round(step * 100)}%, transparent)` }} />
        ))}
        больше публикаций
      </div>
    </div>
  );
}
