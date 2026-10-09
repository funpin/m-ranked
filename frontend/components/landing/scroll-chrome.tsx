"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import Lenis from "lenis";
import { cn } from "@/lib/utils";

export type ChromeSection = { id: string; label: string };

/**
 * Обвязка главной:
 * — инерционная прокрутка (Lenis): ход колеса и тачпада плавно гаснет, а у
 *   верхнего и нижнего края страница мягко останавливается, а не упирается;
 *   при «меньше движения» её нет — прокрутка обычная;
 * — оглавление сверху справа: каждая строка — ссылка на свой раздел. Текущий
 *   раздел крупно, остальные мелко; при смене раздела строки волной меняют
 *   размер, а новая текущая «вкатывается» с той стороны, куда листают.
 *   Под строками фон мягко размыт, и размытие гаснет к краям — текст не
 *   спорит с тем, что под ним;
 * — тонкая линейка у правого края с долей пройденного: бегунок едет вместе
 *   с прокруткой в том же кадре — положение и число пишутся прямо в узлы,
 *   без перерисовки React и без перехода, который отставал от прокрутки.
 * Оглавление и линейка — только на широком экране.
 */
export function ScrollChrome({ sections }: { sections: readonly ChromeSection[] }) {
  const [current, setCurrent] = useState(0);
  const [direction, setDirection] = useState<"down" | "up">("down");
  const frame = useRef(0);
  const currentRef = useRef(0);
  const ruler = useRef<HTMLDivElement>(null);
  const thumb = useRef<HTMLSpanElement>(null);
  const percent = useRef<HTMLElement>(null);

  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const lenis = reduced ? null : new Lenis({ lerp: 0.085, wheelMultiplier: 0.9, anchors: { offset: -80 }, autoRaf: true });
    const measure = () => {
      frame.current = 0;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      const progress = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
      const height = ruler.current?.clientHeight ?? 0;
      // Текущий — последний раздел, чей верх поднялся выше трети экрана.
      // Сначала все чтения разметки, потом записи — без лишнего пересчёта.
      let index = 0;
      sections.forEach((section, position) => {
        const element = document.getElementById(section.id);
        if (element && element.getBoundingClientRect().top < window.innerHeight * 0.35) index = position;
      });
      if (thumb.current) thumb.current.style.transform = `translateY(${progress * height}px)`;
      if (percent.current) percent.current.textContent = `${String(Math.round(progress * 100)).padStart(3, "0")} %`;
      if (index !== currentRef.current) {
        setDirection(index > currentRef.current ? "down" : "up");
        currentRef.current = index;
        setCurrent(index);
      }
    };
    const schedule = () => { if (!frame.current) frame.current = requestAnimationFrame(measure); };
    measure();
    // Lenis сам двигает страницу в своём кадре: бегунок следует за ним в нём же.
    lenis?.on("scroll", measure);
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      cancelAnimationFrame(frame.current);
      lenis?.destroy();
    };
  }, [sections]);

  return (
    <div className="landing-chrome">
      <nav className="landing-index" aria-label="Разделы главной" data-direction={direction}>
        <ol>
          {sections.map((section, index) => (
            <li key={section.id} className={cn(index < current && "is-past", index === current && "is-current", index > current && "is-next")}
              style={{ "--gap": Math.abs(index - current) } as CSSProperties}>
              <a href={`#${section.id}`} aria-current={index === current ? "location" : undefined}><span>{section.label}</span></a>
            </li>
          ))}
        </ol>
      </nav>
      <div className="landing-ruler" aria-hidden="true" ref={ruler}>
        {Array.from({ length: 21 }, (_, tick) => (
          <span key={tick} className={cn("landing-ruler-tick", tick % 5 === 0 && "is-major")} style={{ top: `${tick * 5}%` }} />
        ))}
        <span className="landing-ruler-thumb" ref={thumb}>
          <i ref={percent}>000 %</i>
        </span>
      </div>
    </div>
  );
}
