"use client";

import { useEffect, useRef } from "react";
import { formatStat } from "@/lib/landing";

/** Число досчитывает до значения, когда появляется на экране. Сервер рисует
 *  итоговое значение: без скрипта и при «меньше движения» оно просто стоит. */
export function CountUp({ value, durationMs = 1400 }: { value: number; durationMs?: number }) {
  const element = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const node = element.current;
    if (!node || value <= 0) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let frame = 0;
    // Ниже экрана число заранее сбрасывается: к появлению счёт начнётся с нуля.
    if (node.getBoundingClientRect().top > window.innerHeight) node.textContent = formatStat(0);
    const run = () => {
      const started = performance.now();
      const step = (now: number) => {
        const progress = Math.min(1, (now - started) / durationMs);
        node.textContent = formatStat(value * (1 - (1 - progress) ** 4));
        if (progress < 1) frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    };
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      run();
    }, { threshold: 0.6 });
    observer.observe(node);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      node.textContent = formatStat(value);
    };
  }, [value, durationMs]);

  return <span ref={element}>{formatStat(value)}</span>;
}
