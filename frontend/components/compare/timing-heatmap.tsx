"use client";

import { useState, type KeyboardEvent } from "react";
import { WEEKDAYS, formatInteger, type timingGrid } from "@/lib/compare-dashboard";
import { cn } from "@/lib/utils";

type Grid = ReturnType<typeof timingGrid>;

const describe = (grid: Grid, weekday: number, hour: number) => {
  const cell = grid[weekday]![hour]!;
  return `${WEEKDAYS[weekday]}, ${String(hour).padStart(2, "0")}:00 — ${formatInteger(cell.posts)} публ., `
    + `медиана просмотров за 24 ч: ${formatInteger(cell.views24)}`;
};

/** Тепловая карта «день недели × час выхода»: число публикаций. Ячейка
 *  выбирается курсором, касанием или стрелками; её числа — строкой под
 *  сеткой, а не всплывающей подсказкой, которой нет на телефоне. */
export function TimingHeatmap({ grid, loading = false }: { grid: Grid; loading?: boolean }) {
  const peak = Math.max(1, ...grid.flat().map((cell) => cell.posts));
  const [active, setActive] = useState<[number, number] | null>(null);
  const [focus, setFocus] = useState<[number, number]>([0, 0]);
  const move = (event: KeyboardEvent, weekday: number, hour: number) => {
    const steps: Record<string, [number, number]> = {
      ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1], Home: [0, -hour], End: [0, 23 - hour],
    };
    if (event.key === "Escape") { setActive(null); return; }
    const step = steps[event.key];
    if (!step) return;
    event.preventDefault();
    const next: [number, number] = [Math.min(6, Math.max(0, weekday + step[0])), Math.min(23, Math.max(0, hour + step[1]))];
    setFocus(next);
    setActive(next);
    document.getElementById(`heatmap-${next[0]}-${next[1]}`)?.focus();
  };
  return (
    <div data-testid="timing-heatmap" aria-busy={loading} className={cn("min-w-0 transition-opacity", loading && "opacity-50")}>
      {/* На узком экране сетка прокручивается вбок; ячейки фокусируются сами. */}
      <div className="overflow-x-auto" onPointerLeave={() => setActive(null)}>
        <div className="grid min-w-[560px] gap-[3px]" style={{ gridTemplateColumns: "28px repeat(24, minmax(0, 1fr))" }}
          role="grid" aria-label="Публикации по дню недели и часу выхода, московское время">
          <div className="contents" role="row">
            <span role="columnheader" className="text-muted-foreground text-[10px]" aria-label="День недели" />
            {Array.from({ length: 24 }, (_, hour) => (
              <span key={hour} role="columnheader" aria-label={`${hour}:00`}
                className="text-muted-foreground text-center text-[10px] tabular-nums">{hour % 3 === 0 ? hour : ""}</span>
            ))}
          </div>
          {grid.map((row, weekday) => (
            <div key={weekday} className="contents" role="row">
              <span className="text-muted-foreground self-center text-[11px]" role="rowheader">{WEEKDAYS[weekday]}</span>
              {row.map((cell, hour) => {
                const intensity = cell.posts / peak;
                const selected = active?.[0] === weekday && active[1] === hour;
                return (
                  <span key={hour} id={`heatmap-${weekday}-${hour}`} role="gridcell" aria-label={describe(grid, weekday, hour)}
                    tabIndex={focus[0] === weekday && focus[1] === hour ? 0 : -1}
                    className={cn("aspect-square rounded-[3px] outline-none focus-visible:ring-ring focus-visible:ring-2",
                      selected && "ring-foreground ring-2")}
                    style={{ background: cell.posts ? `color-mix(in oklch, var(--chart-2) ${Math.round(12 + intensity * 88)}%, transparent)` : "var(--muted)" }}
                    onPointerEnter={() => setActive([weekday, hour])}
                    onClick={() => { setFocus([weekday, hour]); setActive([weekday, hour]); }}
                    onFocus={() => { setFocus([weekday, hour]); setActive([weekday, hour]); }}
                    onKeyDown={(event) => move(event, weekday, hour)} />
                );
              })}
            </div>
          ))}
        </div>
      </div>
      <p className="text-foreground mt-2 min-h-5 text-xs tabular-nums" aria-hidden="true" data-testid="heatmap-readout">
        {active ? describe(grid, active[0], active[1])
          : <span className="text-muted-foreground">Наведите на ячейку или нажмите на неё, чтобы увидеть числа</span>}
      </p>
      <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
        <span className="flex items-center gap-2">
          меньше
          {[0.12, 0.35, 0.6, 0.85, 1].map((step) => (
            <span key={step} className="size-3 rounded-[3px]" style={{ background: `color-mix(in oklch, var(--chart-2) ${Math.round(step * 100)}%, transparent)` }} />
          ))}
          больше публикаций
        </span>
        <span>По горизонтали — час выхода, по вертикали — день недели</span>
      </div>
    </div>
  );
}
