"use client";

import dynamic from "next/dynamic";
import { useState, type ReactNode } from "react";
import { Info } from "lucide-react";
import { NOTE_TRIGGER } from "@/components/method-note-trigger";

// Всплывающая часть приезжает по первому касанию: сам позиционер весит около
// 44 КиБ, и в первой загрузке страницы ему делать нечего.
const MethodNotePopover = dynamic(
  () => import("@/components/method-note-popover").then((module) => module.MethodNotePopover),
  { ssr: false },
);

/**
 * Методика — под значком, а не над графиком.
 *
 * Описания того, чем «Всего» отличается от «Прироста» и что означают ромбы,
 * занимали пять строк над каждой картинкой и отодвигали саму картинку за край
 * экрана. Текст никуда не делся: он открывается по значку рядом с заголовком.
 */
export function MethodNote({ title, children }: { title: string; children: ReactNode }) {
  // «none», пока не пришёл указатель или нажатие; нажатие сразу открывает
  // заметку, как только код доедет, поэтому одно нажатие остаётся одним.
  const [activation, setActivation] = useState<"none" | "preload" | "open">("none");

  // Переход фокусом не должен подменять кнопку под самим фокусом, поэтому
  // подгрузку запускает только указатель или настоящее нажатие.
  if (activation === "none") {
    return (
      <button
        type="button"
        className={NOTE_TRIGGER}
        aria-label={`Как считается: ${title}`}
        aria-haspopup="dialog"
        onPointerEnter={() => setActivation("preload")}
        onClick={() => setActivation("open")}
      >
        <Info className="size-4" aria-hidden="true" />
      </button>
    );
  }
  return <MethodNotePopover title={title} defaultOpen={activation === "open"}>{children}</MethodNotePopover>;
}
