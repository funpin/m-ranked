"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { FlaskConical, Server } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import type { ChartName } from "@/lib/methodology-charts";

// Графики и их данные приезжают, только когда рисунок подходит к экрану:
// в первой загрузке статьи ни recharts, ни данных графиков нет.
const Chart = dynamic(() => import("./analysis-charts").then((module) => module.AnalysisChart), {
  ssr: false,
  loading: () => <Skeleton className="h-64 w-full" role="status" aria-label="Загрузка графика" />,
});

/** Рисунок статьи методологии: заголовок, происхождение данных, график и подпись. */
export function Figure({ chart, title, source = "reference", children }: {
  chart: ChartName; title: string; source?: "reference" | "production" | "research"; children?: ReactNode;
}) {
  const frame = useRef<HTMLElement>(null);
  const [near, setNear] = useState(false);

  useEffect(() => {
    const node = frame.current;
    // IntersectionObserver есть во всех поддерживаемых браузерах.
    if (!node) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) { setNear(true); observer.disconnect(); }
    }, { rootMargin: "400px 0px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const origin = source === "reference"
    ? { icon: FlaskConical, text: "эталонный ряд и настоящий детектор" }
    : source === "production"
      ? { icon: Server, text: "данные сервера, публикации за 30 суток" }
      : { icon: Server, text: "проверка на реальных данных" };
  const Icon = origin.icon;
  return (
    <figure ref={frame} data-figure={chart}
      className="bg-card ring-foreground/10 my-8 grid gap-3 rounded-2xl p-4 ring-1 sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="font-heading text-base font-semibold tracking-tight">{title}</p>
        <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
          <Icon className="size-3.5" aria-hidden="true" />{origin.text}
        </span>
      </div>
      <div>{near ? <Chart chart={chart} /> : <Skeleton className="h-64 w-full" aria-hidden="true" />}</div>
      {children ? <figcaption className="text-muted-foreground text-sm leading-relaxed [&>p]:my-0">{children}</figcaption> : null}
    </figure>
  );
}
