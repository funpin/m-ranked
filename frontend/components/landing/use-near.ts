"use client";

import { useEffect, useState, type RefObject } from "react";

/** Становится true один раз, когда элемент подъезжает к экрану (с запасом
 *  margin): так тяжёлые фрагменты грузятся к моменту, когда их увидят. */
export function useNear(target: RefObject<Element | null>, margin = "320px 0px") {
  const [near, setNear] = useState(false);
  useEffect(() => {
    const node = target.current;
    if (!node || near) return;
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      setNear(true);
    }, { rootMargin: margin });
    observer.observe(node);
    return () => observer.disconnect();
  }, [target, margin, near]);
  return near;
}
