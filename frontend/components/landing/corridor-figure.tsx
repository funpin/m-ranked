import type { ReactNode } from "react";
import type { CorridorModel, CorridorShapeId } from "@/lib/landing";
import { cn } from "@/lib/utils";

export const LEVEL_TONES = ["var(--chart-1)", "var(--chart-10)", "var(--chart-3)", "var(--destructive)"] as const;
export const toneOf = (level: number) => LEVEL_TONES[level] ?? LEVEL_TONES[0];

/** Схема автоматического анализа. Кривую поста передаёт вызывающий: до
 *  загрузки анимации это обычный path, после — анимированный. */
export function CorridorFigure({ model, active, curve, onSelect, figureRef }: {
  model: CorridorModel; active: CorridorShapeId; curve: ReactNode; onSelect?: (id: CorridorShapeId) => void;
  figureRef?: React.Ref<HTMLDivElement>;
}) {
  const { frame: CORRIDOR, band: BAND, crowd: CROWD } = model;
  const shape = model.shapes.find((item) => item.id === active) ?? model.shapes[0]!;
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] lg:items-center" data-testid="norm-corridor">
      <div ref={figureRef} className="landing-tile relative overflow-hidden p-4 sm:p-7">
        <div className="text-muted-foreground mb-2 flex items-center justify-between text-[11px] tracking-wide uppercase">
          <span>просмотры</span><span>схема · не данные</span>
        </div>
        <svg viewBox={`0 0 ${CORRIDOR.width} ${CORRIDOR.height}`} className="h-auto w-full" role="img"
          aria-label={`Схема: ${shape.title.toLowerCase()} относительно обычного разброса площадки`}>
          <defs>
            <linearGradient id="corridor-band" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="var(--chart-2)" stopOpacity="0.26" />
              <stop offset="1" stopColor="var(--chart-2)" stopOpacity="0.06" />
            </linearGradient>
          </defs>
          {[0.25, 0.5, 0.75].map((fraction) => {
            const y = CORRIDOR.bottom - (CORRIDOR.bottom - CORRIDOR.top) * fraction;
            return <line key={fraction} x1={CORRIDOR.left} x2={CORRIDOR.right} y1={y} y2={y} stroke="var(--border)" strokeDasharray="2 6" />;
          })}
          <line x1={CORRIDOR.left} x2={CORRIDOR.right} y1={CORRIDOR.bottom} y2={CORRIDOR.bottom} stroke="var(--border)" />
          <path d={BAND.area} fill="url(#corridor-band)" />
          {/* Живые посты площадки: все разные, но в пределах разброса. */}
          {CROWD.map((d, index) => <path key={index} d={d} fill="none" stroke="var(--muted-foreground)" strokeOpacity={0.35} strokeWidth={1} />)}
          <text x={CORRIDOR.right} y={BAND.labelY} textAnchor="end" className="fill-muted-foreground text-[11px]">обычный разброс площадки</text>
          {curve}
          <text x={CORRIDOR.left} y={CORRIDOR.bottom + 22} className="fill-muted-foreground text-[11px]">публикация</text>
          <text x={CORRIDOR.right} y={CORRIDOR.bottom + 22} textAnchor="end" className="fill-muted-foreground text-[11px]">возраст поста →</text>
        </svg>
      </div>

      <div className="grid gap-5">
        <div role="radiogroup" aria-label="Форма роста" className="flex flex-wrap gap-2">
          {model.shapes.map((item) => {
            const selected = item.id === active;
            const tone = toneOf(item.level);
            return (
              <button key={item.id} type="button" role="radio" aria-checked={selected} onClick={() => onSelect?.(item.id)}
                style={selected ? { background: `color-mix(in oklch, ${tone} 14%, transparent)`, boxShadow: `inset 0 0 0 2px ${tone}` } : undefined}
                className={cn("min-h-9 rounded-full px-3.5 text-sm font-medium ring-1 transition-[background-color,color,box-shadow] duration-300 outline-none",
                  "focus-visible:ring-ring/60 focus-visible:ring-2",
                  selected ? "text-foreground ring-transparent" : "text-muted-foreground ring-foreground/10 hover:text-foreground")}>
                {item.title}
              </button>
            );
          })}
        </div>
        <p className="text-foreground/90 min-h-[3lh] text-base leading-relaxed" aria-live="polite">{shape.text}</p>
        <ol className="grid gap-1.5" aria-label="Уровни анализа">
          {model.levels.map((item) => {
            const current = item.level === shape.level;
            return (
              <li key={item.level} className={cn("flex items-center gap-3 rounded-lg px-2 py-1.5 transition-colors duration-300", current && "bg-muted/70")}>
                <span className="flex h-2 w-16 shrink-0 gap-0.5" aria-hidden="true">
                  {[0, 1, 2, 3].map((bar) => (
                    <span key={bar} className="flex-1 rounded-full"
                      style={{ background: bar <= item.level && (item.level > 0 || bar === 0) ? toneOf(item.level) : "var(--muted)" }} />
                  ))}
                </span>
                <span className={cn("text-sm", current ? "text-foreground font-medium" : "text-muted-foreground")}>
                  {item.title}<span className="text-muted-foreground font-normal"> — {item.text}</span>
                </span>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

/** Неподвижная кривая: до загрузки анимации и в разметке с сервера. */
export function StaticCurve({ d, tone }: { d: string; tone: string }) {
  return <path d={d} fill="none" stroke={tone} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" />;
}
