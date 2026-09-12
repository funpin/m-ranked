"use client";

import { useEffect, useRef } from "react";
import { formatMetric } from "@/lib/format";

/**
 * Counts a measurement up to its value once, on first paint.
 *
 * The server renders the final value, so the markup is correct without
 * JavaScript and hydration has nothing to reconcile. The count-up then runs by
 * writing textContent from a single rAF loop rather than through state: an
 * overview screen carries dozens of these, and re-rendering each of them sixty
 * times a second would cost far more than the effect is worth.
 *
 * No layout shift: the figure reserves its width through tabular digits.
 * Respects prefers-reduced-motion by leaving the rendered value alone.
 */
export function AnimatedNumber({ value, fraction = false, durationMs = 620 }: {
  value: number | null;
  fraction?: boolean;
  durationMs?: number;
}) {
  const element = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const node = element.current;
    if (!node || value === null || value === 0) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let frame = 0;
    const started = performance.now();
    const step = (now: number) => {
      const progress = Math.min(1, (now - started) / durationMs);
      // Ease out, so the figure settles rather than stopping dead.
      node.textContent = formatMetric(Math.round(value * (1 - (1 - progress) ** 3)), fraction);
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(frame);
      node.textContent = formatMetric(value, fraction);
    };
  }, [value, fraction, durationMs]);

  return <span ref={element}>{formatMetric(value, fraction)}</span>;
}
