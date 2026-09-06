"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

const Visibility = createContext<{ hidden: Set<string>; toggle: (id: string) => void }>({
  hidden: new Set(), toggle: () => undefined,
});

export function ComparisonVisibility({ children }: { children: ReactNode }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  return <Visibility.Provider value={{ hidden, toggle(id) {
    setHidden((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  } }}>{children}</Visibility.Provider>;
}

export const useComparisonVisibility = () => useContext(Visibility);
