"use client";

import { useId, useMemo, type CSSProperties } from "react";
import { AnimatePresence, LayoutGroup } from "motion/react";
import * as m from "motion/react-m";
import { cn } from "@/lib/utils";

function graphemes(text: string) {
  if (typeof Intl.Segmenter === "function") {
    return Array.from(new Intl.Segmenter("ru", { granularity: "grapheme" }).segment(text), (part) => part.segment);
  }
  return Array.from(text);
}

const MORPH = { type: "spring", stiffness: 125, damping: 25, mass: 0.4 } as const;
const HIDDEN = { opacity: 0, scale: 0.8, filter: "blur(10px)" } as const;
// Фильтр снимается в конце: буквы с blur(0px) рисовались бы мягче.
const SHOWN = { opacity: 1, scale: 1, filter: "blur(0px)", transitionEnd: { filter: "none" } } as const;

/**
 * Крупный заголовок страницы в духе MorphingText из animate-ui.
 *
 * Первое появление — проявление букв из размытия на CSS (класс
 * title-reveal в globals.css): оно видно с первой отрисовкой, без ожидания
 * скриптов, и не задерживает LCP. Когда текст меняется на клиенте (вкладки
 * панели, переключение режима), общие буквы перестраиваются на новые места,
 * лишние растворяются, новые проявляются — морфинг через layoutId.
 * Буквы сгруппированы по словам: заголовок переносится между словами, а не
 * посреди слова, как у исходного компонента с отдельными inline-block буквами.
 */
export function PageTitle({ text, className }: { text: string; className?: string }) {
  const id = useId();
  const words = useMemo(() => {
    const counts = new Map<string, number>();
    let index = 0;
    return text.split(/\s+/).filter(Boolean).map((word) => graphemes(word).map((char) => {
      const seen = (counts.get(char) ?? 0) + 1;
      counts.set(char, seen);
      return { char, key: `${id}-${char}-${seen}`, index: index++ };
    }));
  }, [text, id]);
  return (
    <span className={cn("title-reveal", className)}>
      <span className="sr-only">{text}</span>
      <LayoutGroup id={id}>
        <AnimatePresence mode="popLayout" initial={false}>
          {words.flatMap((word, wordIndex) => [
            <span key={`w-${word[0]?.key}`} className="inline-block whitespace-nowrap" aria-hidden="true">
              {word.map(({ char, key, index }) => (
                <m.span key={key} layoutId={key} className="title-reveal-char inline-block"
                  style={{ "--i": index } as CSSProperties}
                  initial={HIDDEN} animate={SHOWN} exit={HIDDEN} transition={MORPH}>
                  {char}
                </m.span>
              ))}
            </span>,
            wordIndex < words.length - 1 ? <span key={`s-${wordIndex}`} aria-hidden="true"> </span> : null,
          ])}
        </AnimatePresence>
      </LayoutGroup>
    </span>
  );
}
