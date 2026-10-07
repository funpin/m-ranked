import { cn } from "@/lib/utils";

function graphemes(text: string) {
  if (typeof Intl.Segmenter === "function") {
    return Array.from(new Intl.Segmenter("ru", { granularity: "grapheme" }).segment(text), (part) => part.segment);
  }
  return Array.from(text);
}

/**
 * Крупный заголовок страницы: буквы проявляются из размытия и вырастают из
 * 80 % — эффект MorphingText из animate-ui, сделанный на CSS (класс
 * title-reveal в globals.css). Он виден с первой отрисовкой, без скриптов.
 *
 * Волна по буквам занимает одно и то же время при любой длине заголовка:
 * у длинного названия вуза буквы просто идут чаще. При смене текста
 * заголовок пересоздаётся целиком (key) и проявляется заново — старые
 * буквы не досматривают исчезновение поверх новых.
 * Буквы сгруппированы по словам: перенос — между словами.
 */
export function PageTitle({ text, className }: { text: string; className?: string }) {
  const words = text.split(/\s+/).filter(Boolean).map((word) => graphemes(word));
  const total = words.reduce((sum, word) => sum + word.length, 0);
  let index = 0;
  return (
    <span key={text} className={cn("title-reveal", className)} style={{ "--n": Math.max(1, total) } as React.CSSProperties}>
      <span className="sr-only">{text}</span>
      {words.map((word, wordIndex) => (
        <span key={wordIndex} aria-hidden="true">
          <span className="inline-block whitespace-nowrap">
            {word.map((char) => {
              const i = index++;
              return <span key={i} className="title-reveal-char inline-block" style={{ "--i": i } as React.CSSProperties}>{char}</span>;
            })}
          </span>
          {wordIndex < words.length - 1 ? " " : null}
        </span>
      ))}
    </span>
  );
}
