"use client";

import { useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { Icon } from "@/components/icon-sprite";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import { NOTE_TRIGGER } from "@/components/method-note-trigger";

// Сколько указатель может быть вне значка и заметки, прежде чем она закроется:
// хватает, чтобы перевести его со значка на саму заметку.
const LEAVE_DELAY_MS = 150;

/**
 * Всплывающая половина заметки о методике. Загружается по требованию:
 * позиционер Base UI весит около 44 КиБ, а заметка стоит на каждой странице
 * с графиком, так что иначе он попадал бы в первую загрузку всех маршрутов.
 *
 * Открытие управляется здесь. Заметка монтируется уже под указателем (первое
 * наведение открывает её сразу), и Base UI этого входа не видел, а потому не
 * закрывал её при уходе указателя: на карточках обзора подсказки копились.
 * Уход мышью и со значка, и с самой заметки закрывает её всегда.
 */
export function MethodNotePopover({ title, defaultOpen, children }: {
  title: string; defaultOpen?: boolean; children: ReactNode;
}) {
  const [open, setOpen] = useState(Boolean(defaultOpen));
  const inside = useRef({ trigger: Boolean(defaultOpen), popup: false });
  const timer = useRef<number | undefined>(undefined);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    // Код заметки догружается по первому наведению, и указатель мог уйти, пока
    // она грузилась: тогда открывать её не для кого.
    if (defaultOpen) {
      timer.current = window.setTimeout(() => {
        if (!trigger.current?.matches(":hover")) {
          inside.current.trigger = false;
          setOpen(false);
        }
      }, LEAVE_DELAY_MS);
    }
    return () => window.clearTimeout(timer.current);
  }, [defaultOpen]);

  const enter = (part: "trigger" | "popup") => (event: PointerEvent) => {
    if (event.pointerType !== "mouse") return;
    inside.current[part] = true;
    window.clearTimeout(timer.current);
  };
  const leave = (part: "trigger" | "popup") => (event: PointerEvent) => {
    if (event.pointerType !== "mouse") return;
    inside.current[part] = false;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      if (!inside.current.trigger && !inside.current.popup) setOpen(false);
    }, LEAVE_DELAY_MS);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger ref={trigger} openOnHover delay={100} className={NOTE_TRIGGER} aria-label={`Как считается: ${title}`}
        onPointerEnter={enter("trigger")} onPointerLeave={leave("trigger")}>
        <Icon name="info" className="size-4" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 leading-relaxed"
        onPointerEnter={enter("popup")} onPointerLeave={leave("popup")}>
        <PopoverTitle className="sr-only">{title}</PopoverTitle>
        <PopoverDescription>{children}</PopoverDescription>
      </PopoverContent>
    </Popover>
  );
}
