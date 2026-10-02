"use client";

import { useEffect, type RefObject } from "react";

/** Marks a sticky element with data-stuck while it rests against its sticky edge. */
export function useStuck(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const style = getComputedStyle(node);
      const top = Number.parseFloat(style.top);
      const stuck = style.position === "sticky" && Number.isFinite(top)
        && node.getBoundingClientRect().top <= top + 0.5;
      node.toggleAttribute("data-stuck", stuck);
    };
    const schedule = () => { if (!frame) frame = window.requestAnimationFrame(update); };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [ref]);
}
