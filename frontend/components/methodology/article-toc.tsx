"use client";

import { useEffect, useRef, useState } from "react";
import type { TocEntry } from "@/lib/methodology";
import { cn } from "@/lib/utils";

/** Оглавление статьи. Список приходит с сервера; скрипт только подсвечивает
 *  раздел, который сейчас читают. */
export function ArticleToc({ entries }: { entries: readonly TocEntry[] }) {
  const [current, setCurrent] = useState<string | null>(null);
  const list = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const observer = new IntersectionObserver((items) => {
      const visible = items.filter((item) => item.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible[0]) setCurrent(visible[0].target.id);
    }, { rootMargin: "-80px 0px -65% 0px" });
    for (const entry of entries) {
      const heading = document.getElementById(entry.id);
      if (heading) observer.observe(heading);
    }
    return () => observer.disconnect();
  }, [entries]);

  // Длинное оглавление прокручивается само: текущий раздел не уходит за край панели.
  useEffect(() => {
    if (!current) return;
    // Прокручивается только панель, не страница: scrollIntoView сдвинул бы и окно.
    const link = list.current?.querySelector<HTMLElement>(`[aria-current="location"]`);
    const panel = list.current?.closest<HTMLElement>("[data-toc-scroll]");
    if (!link || !panel) return;
    const top = link.getBoundingClientRect().top - panel.getBoundingClientRect().top + panel.scrollTop;
    if (top < panel.scrollTop) panel.scrollTop = top - 8;
    else if (top + link.offsetHeight > panel.scrollTop + panel.clientHeight) panel.scrollTop = top + link.offsetHeight - panel.clientHeight + 8;
  }, [current]);

  if (entries.length < 2) return null;
  return (
    <nav aria-label="На этой странице" className="grid gap-3 text-sm" data-testid="article-toc">
      <p className="text-muted-foreground text-xs font-medium tracking-[0.12em] uppercase">На этой странице</p>
      <ul ref={list} className="border-border grid gap-0.5 border-l">
        {entries.map((entry) => (
          <li key={entry.id}>
            <a href={`#${entry.id}`} aria-current={current === entry.id ? "location" : undefined}
              className={cn("-ml-px block border-l py-1 transition-colors", entry.level === 3 ? "pl-6" : "pl-3",
                current === entry.id ? "border-foreground text-foreground" : "text-muted-foreground hover:text-foreground border-transparent")}>
              {entry.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
