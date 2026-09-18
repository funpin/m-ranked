"use client";

import { useEffect, useRef } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import Link from "@/components/native-link";
import { selectedDayHref } from "@/lib/day-selection";
import { X } from "lucide-react";

const WEEKDAY = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

function dayLabel(day: string) {
  const date = new Date(`${day}T00:00:00`);
  return `${WEEKDAY[date.getDay()]} ${date.getDate()}.${String(date.getMonth() + 1).padStart(2, "0")}`;
}

/** Explains the selected day and restores the median cohort spotlight. */
export function DaySpotlight({ day, mode = "median" }: { day?: string; mode?: "median" | "total" }) {
  const pathname = usePathname();
  const search = useSearchParams();
  const previous = useRef<string | null>(null);
  useEffect(() => {
    if (!day || mode !== "median") { previous.current = null; return; }
    if (previous.current === day) return;
    previous.current = day;
    const first = document.querySelector<HTMLElement>(`[data-published-day="${CSS.escape(day)}"]`);
    if (!first) return;
    first.scrollIntoView({
      block: "center", inline: "nearest",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
    });
    first.querySelector<HTMLAnchorElement>("a")?.focus({ preventScroll: true });
  }, [day, mode]);
  if (!day) return null;
  return (
    <>
    {mode === "median" ? <style>{`[data-published-day]{transition:background-color .2s,opacity .2s}
      [data-published-day]:not([data-published-day="${day}"]){opacity:.45!important}
      [data-published-day="${day}"]{background:var(--accent)}`}</style> : null}
    <div className="mb-3 flex flex-wrap items-center gap-2 text-sm" role="status">
      <span className="bg-accent text-accent-foreground inline-flex items-center rounded-full px-2.5 py-0.5 font-medium tabular">
        {dayLabel(day)}
      </span>
      <span className="text-muted-foreground">{mode === "median" ? "публикации этого дня" : "прирост за сутки показан рядом с реакциями и просмотрами"}</span>
      <Link href={selectedDayHref(pathname, search.toString())} scroll={false}
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 rounded-md bg-transparent underline underline-offset-4">
        <X className="size-3.5" aria-hidden="true" />{mode === "median" ? "показать все" : "скрыть прирост"}
      </Link>
    </div>
    </>
  );
}
