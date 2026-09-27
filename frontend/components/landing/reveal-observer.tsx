"use client";

import { useEffect } from "react";
import { formatStat } from "@/lib/format";

const SELECTOR = ".landing-rise, .landing-pop, .landing-slide, .landing-widen, .landing-tilt, .landing-ticks, .landing-draw";

/** Число досчитывает от нуля до значения вместе с появлением. Сервер рисует
 *  итоговое значение: без скрипта и при «меньше движения» оно просто стоит. */
function countUp(node: HTMLElement) {
  const value = Number(node.dataset.count);
  if (!(value > 0)) return;
  const started = performance.now();
  const step = (now: number) => {
    const progress = Math.min(1, (now - started) / 1400);
    node.textContent = formatStat(value * (1 - (1 - progress) ** 4));
    if (progress < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/** Запускает появление элементов главной один раз — когда элемент впервые
 *  доезжает до экрана. Дальше он просто стоит: прокрутка вверх и вниз его не
 *  перезапускает, пока страницу не перезагрузят. Карточки лент проявляются
 *  разом, когда до экрана доезжает сама лента: иначе те, что правее края
 *  окна, остались бы невидимыми при листании. Блоки, пришедшие позже потоком
 *  (графики), подхватываются по мере появления в разметке. */
export function RevealObserver() {
  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const root = document.documentElement;
    const seen = new WeakSet<Element>();
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);
        const group = entry.target.matches(".landing-ribbon-track")
          ? entry.target.querySelectorAll<HTMLElement>(".landing-slide")
          : [entry.target as HTMLElement];
        for (const element of group) {
          element.classList.add("is-in");
          for (const number of element.querySelectorAll<HTMLElement>("[data-count]")) countUp(number);
        }
      }
    }, { rootMargin: "0px 0px -12% 0px", threshold: 0.01 });

    const scan = () => {
      for (const element of document.querySelectorAll(SELECTOR)) {
        if (element.classList.contains("is-in")) continue;
        const target = element.matches(".landing-slide") ? element.closest(".landing-ribbon-track") ?? element : element;
        if (seen.has(target)) {
          // Лента уже проявилась, а карточка пришла позже — показать сразу.
          if (target !== element && target.querySelector(".landing-slide.is-in")) element.classList.add("is-in");
          continue;
        }
        seen.add(target);
        observer.observe(target);
      }
    };
    // Доигравшая анимация снимается целиком: иначе на тексте остаётся
    // blur(0px) — отдельный слой, на котором шрифт в некоторых браузерах
    // рисуется мягче.
    const done = (event: AnimationEvent) => {
      const target = event.target as HTMLElement;
      if (target.classList.contains("is-in")) target.classList.add("is-done");
    };
    document.addEventListener("animationend", done);
    // Прятать элементы можно, только когда наблюдатель готов их показать.
    root.classList.add("reveal-ready");
    scan();
    // Графики меняют разметку часто — пересмотр не чаще раза в кадр.
    let frame = 0;
    const mutations = new MutationObserver(() => {
      if (!frame) frame = requestAnimationFrame(() => { frame = 0; scan(); });
    });
    mutations.observe(document.body, { childList: true, subtree: true });
    return () => {
      document.removeEventListener("animationend", done);
      cancelAnimationFrame(frame);
      mutations.disconnect();
      observer.disconnect();
      root.classList.remove("reveal-ready");
    };
  }, []);
  return null;
}
