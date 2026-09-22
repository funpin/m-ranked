"use client";

import type { ReactNode } from "react";
import { Icon } from "@/components/icon-sprite";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import { NOTE_TRIGGER } from "@/components/method-note-trigger";

/**
 * Всплывающая половина заметки о методике. Загружается по требованию:
 * позиционер Base UI весит около 44 КиБ, а заметка стоит на каждой странице
 * с графиком, так что иначе он попадал бы в первую загрузку всех маршрутов.
 */
export function MethodNotePopover({ title, defaultOpen, children }: {
  title: string; defaultOpen?: boolean; children: ReactNode;
}) {
  return (
    <Popover defaultOpen={defaultOpen}>
      <PopoverTrigger className={NOTE_TRIGGER} aria-label={`Как считается: ${title}`}>
        <Icon name="info" className="size-4" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 leading-relaxed">
        <PopoverTitle className="sr-only">{title}</PopoverTitle>
        <PopoverDescription>{children}</PopoverDescription>
      </PopoverContent>
    </Popover>
  );
}
