"use client";

import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

/** Всплывающая половина панели «Фильтры». Загружается по требованию, как и
 *  заметка о методике: позиционер Base UI в первой загрузке страницы не нужен. */
export function TypesPopoverPanel({ label, defaultOpen, onOpenChange, children }: {
  label: ReactNode; defaultOpen?: boolean; onOpenChange?: (open: boolean) => void; children: ReactNode;
}) {
  return (
    <Popover defaultOpen={defaultOpen} onOpenChange={(open) => onOpenChange?.(open)}>
      <PopoverTrigger render={<Button type="button" variant="outline" size="sm" className="h-8 w-full text-sm" />}>{label}</PopoverTrigger>
      <PopoverContent align="end" className="w-64 gap-4 text-sm">{children}</PopoverContent>
    </Popover>
  );
}
