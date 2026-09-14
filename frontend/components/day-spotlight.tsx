"use client";

import { useEffect, useRef } from "react";
import { clearFocusedDay, useFocusedDay } from "@/lib/day-focus";
import { X } from "lucide-react";

const WEEKDAY = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

function dayLabel(day: string) {
  const date = new Date(`${day}T00:00:00`);
  return `${WEEKDAY[date.getDay()]} ${date.getDate()}.${String(date.getMonth() + 1).padStart(2, "0")}`;
}

/**
 * Подсветка публикаций выбранного на графике дня и прыжок к первой из них.
 *
 * Строки таблицы отрисованы на сервере и React ими не владеет, поэтому
 * подсветка приезжает правилом стиля по атрибуту дня, а не переписыванием
 * разметки: так таблица остаётся серверной и не попадает в клиентский код.
 */
export function DaySpotlight() {
  const day = useFocusedDay();
  const previous = useRef<string | null>(null);

  useEffect(() => {
    if (!day || previous.current === day) { previous.current = day; return; }
    previous.current = day;
    const first = document.querySelector<HTMLElement>(`[data-published-day="${CSS.escape(day)}"]`);
    if (!first) return;
    first.scrollIntoView({
      block: "center", inline: "nearest",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
    });
    first.querySelector<HTMLAnchorElement>("a")?.focus({ preventScroll: true });
  }, [day]);

  if (!day) return null;
  return <>
    <style>{`[data-published-day]{transition:background-color .2s}
      [data-published-day]:not([data-published-day="${day}"]){opacity:.45}
      [data-published-day="${day}"]{background:var(--accent)}`}</style>
    <div className="mb-3 flex flex-wrap items-center gap-2 text-sm" role="status">
      <span className="bg-accent text-accent-foreground inline-flex items-center rounded-full px-2.5 py-0.5 font-medium tabular">
        {dayLabel(day)}
      </span>
      <span className="text-muted-foreground">публикации этого дня</span>
      <button type="button" onClick={clearFocusedDay}
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 rounded-md bg-transparent underline underline-offset-4">
        <X className="size-3.5" aria-hidden="true" />показать все
      </button>
    </div>
  </>;
}
