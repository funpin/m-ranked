"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export type RibbonSlide = { id: string; label: string; width: string; content: ReactNode };

/**
 * Лента карточек аккаунта: цифры, динамика, анализ и сравнение стоят в ряд и
 * листаются вбок (scroll-snap), а не громоздятся друг под другом над
 * таблицей постов. Сверху — сегментный переключатель с текущей карточкой и
 * стрелки; на телефоне ленту листают пальцем.
 *
 * Карточки остаются в документе целиком: поиск по странице, ссылки внутрь и
 * чтение с экрана работают как раньше, лента лишь задаёт их расположение.
 */
export function AccountRibbon({ slides, label }: { slides: readonly RibbonSlide[]; label: string }) {
  const scroller = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(slides[0]?.id ?? "");
  const activeRef = useRef(active);
  // Карточка, выбранная кнопкой: пока лента до неё доезжает, промежуточные
  // положения не перебивают выбор (а у правого края — и после).
  const pinned = useRef<string | null>(null);
  useEffect(() => { activeRef.current = active; }, [active]);
  const [edges, setEdges] = useState({ start: true, end: slides.length < 2 });

  useEffect(() => {
    const root = scroller.current;
    if (!root) return;
    const update = () => {
      const max = root.scrollWidth - root.clientWidth;
      setEdges({ start: root.scrollLeft <= 4, end: root.scrollLeft >= max - 4 });
      // Текущая остаётся текущей, пока видна целиком (выбранную кнопкой
      // карточку у правого края не перебивает соседняя); иначе — самая левая
      // карточка, видная больше чем наполовину.
      const box = root.getBoundingClientRect();
      const cards = [...root.querySelectorAll<HTMLElement>("[data-ribbon-slide]")];
      const shown = (card: HTMLElement) => {
        const rect = card.getBoundingClientRect();
        return (Math.min(rect.right, box.right) - Math.max(rect.left, box.left)) / rect.width;
      };
      if (pinned.current) return;
      const kept = cards.find((card) => card.dataset.ribbonSlide === activeRef.current && shown(card) > 0.95);
      const current = kept ?? cards.find((card) => shown(card) > 0.5);
      if (current?.dataset.ribbonSlide) setActive(current.dataset.ribbonSlide);
    };
    const settle = () => { pinned.current = null; };
    const release = () => { pinned.current = null; };
    update();
    root.addEventListener("scroll", update, { passive: true });
    root.addEventListener("scrollend", settle);
    root.addEventListener("wheel", release, { passive: true });
    root.addEventListener("touchstart", release, { passive: true });
    root.addEventListener("keydown", release);
    const observer = new ResizeObserver(update);
    observer.observe(root);
    return () => {
      root.removeEventListener("scroll", update);
      root.removeEventListener("scrollend", settle);
      root.removeEventListener("wheel", release);
      root.removeEventListener("touchstart", release);
      root.removeEventListener("keydown", release);
      observer.disconnect();
    };
  }, [slides.length]);

  const go = (id: string) => {
    const root = scroller.current;
    const card = root?.querySelector<HTMLElement>(`[data-ribbon-slide="${id}"]`);
    if (!root || !card) return;
    pinned.current = id;
    // Без прокрутки scrollend не придёт: запасной срок снятия закрепа.
    window.setTimeout(() => { if (pinned.current === id) pinned.current = null; }, 1200);
    root.scrollTo({ left: root.scrollLeft + card.getBoundingClientRect().left - root.getBoundingClientRect().left - 4, behavior: "smooth" });
    setActive(id);
  };
  const step = (direction: 1 | -1) => {
    const index = slides.findIndex((slide) => slide.id === active);
    const next = slides[Math.min(slides.length - 1, Math.max(0, index + direction))];
    if (next) go(next.id);
  };

  return (
    <section aria-label={label} className="min-w-0" data-testid="account-ribbon">
      <div className="mb-3 flex items-center justify-between gap-3">
        <nav aria-label="Разделы карточки" className="bg-muted/70 inline-flex max-w-full overflow-x-auto rounded-lg p-0.5 [scrollbar-width:none]">
          {slides.map((slide) => (
            <button key={slide.id} type="button" onClick={() => go(slide.id)} aria-current={slide.id === active ? "true" : undefined}
              className={cn("rounded-md px-3 py-1 text-xs font-medium whitespace-nowrap transition-colors focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none",
                slide.id === active ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
              {slide.label}
            </button>
          ))}
        </nav>
        <div className="hidden shrink-0 gap-1 sm:flex">
          <button type="button" aria-label="Предыдущая карточка" disabled={edges.start} onClick={() => step(-1)}
            className="border-border hover:bg-muted inline-flex size-7 items-center justify-center rounded-md border transition-colors disabled:opacity-40">
            <ChevronLeft className="size-4" aria-hidden="true" />
          </button>
          <button type="button" aria-label="Следующая карточка" disabled={edges.end} onClick={() => step(1)}
            className="border-border hover:bg-muted inline-flex size-7 items-center justify-center rounded-md border transition-colors disabled:opacity-40">
            <ChevronRight className="size-4" aria-hidden="true" />
          </button>
        </div>
      </div>
      {/* Край ленты гаснет, пока за ним есть карточки: обрезанная карточка
          читается как «дальше есть ещё», а не как поломка вёрстки. */}
      <div ref={scroller} tabIndex={0} role="region" aria-label={`${label}: листается вбок`}
        style={{ maskImage: `linear-gradient(to right, ${edges.start ? "#000" : "transparent"}, #000 ${edges.start ? "0" : "2.5rem"}, #000 calc(100% - ${edges.end ? "0px" : "3.5rem"}), ${edges.end ? "#000" : "transparent"})` }}
        className="focus-visible:ring-ring/50 -mx-1 flex snap-x snap-mandatory items-stretch gap-4 overflow-x-auto overscroll-x-contain scroll-smooth px-1 pb-3 outline-none focus-visible:ring-[3px] [scrollbar-width:thin] motion-reduce:scroll-auto">
        {slides.map((slide) => (
          <div key={slide.id} data-ribbon-slide={slide.id} className={cn("flex min-w-0 shrink-0 snap-start flex-col", slide.width)}>
            {slide.content}
          </div>
        ))}
      </div>
    </section>
  );
}
