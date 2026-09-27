"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/** Горизонтальная лента в духе галерей Apple: карточки уходят за правый край
 *  окна, листаются жестом, колесом, клавиатурой или круглыми стрелками.
 *  Сама лента — обычная прокрутка со снапом: без скрипта она тоже работает. */
export function Ribbon({ label, children, className, testId, fit = false }: {
  label: string; children: ReactNode; className?: string; testId?: string;
  /** Широкий экран: карточки помещаются — обычная сетка без прокрутки. */
  fit?: boolean;
}) {
  const track = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ start: true, end: false });

  const measure = useCallback(() => {
    const node = track.current;
    if (!node) return;
    setEdges({ start: node.scrollLeft < 8, end: node.scrollLeft + node.clientWidth > node.scrollWidth - 8 });
  }, []);

  useEffect(() => {
    const node = track.current;
    if (!node) return;
    const frame = requestAnimationFrame(measure);
    node.addEventListener("scroll", measure, { passive: true });
    const sizes = new ResizeObserver(measure);
    sizes.observe(node);
    return () => { cancelAnimationFrame(frame); node.removeEventListener("scroll", measure); sizes.disconnect(); };
  }, [measure]);

  const step = (direction: 1 | -1) => {
    const node = track.current;
    const item = node?.querySelector<HTMLElement>(".landing-ribbon-item");
    if (!node || !item) return;
    node.scrollBy({ left: direction * (item.offsetWidth + 16), behavior: "smooth" });
  };

  return (
    <div className={cn("landing-ribbon grid gap-5", fit && "landing-ribbon--fit", className)}>
      <div ref={track} role="region" aria-label={label} tabIndex={0} data-testid={testId}
        className="landing-ribbon-track focus-visible:ring-ring/50 flex snap-x snap-mandatory gap-4 overflow-x-auto overscroll-x-contain pb-2 outline-none focus-visible:ring-2">
        {children}
      </div>
      {/* Всё поместилось — листать нечего, стрелки не нужны. */}
      <div className={cn("landing-ribbon-controls flex justify-end gap-3", edges.start && edges.end && "hidden")}>
        {([[-1, "Назад", ChevronLeft, edges.start], [1, "Дальше", ChevronRight, edges.end]] as const).map(([direction, name, Icon, disabled]) => (
          <button key={name} type="button" aria-label={`${label}: ${name.toLowerCase()}`} disabled={disabled} onClick={() => step(direction)}
            className="bg-muted/80 text-foreground hover:bg-muted focus-visible:ring-ring/60 grid size-10 place-items-center rounded-full outline-none transition-[background-color,opacity] focus-visible:ring-2 disabled:opacity-35">
            <Icon className="size-5" aria-hidden="true" />
          </button>
        ))}
      </div>
    </div>
  );
}
