"use client";

import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { TableRow } from "@/components/ui/table";

/**
 * Строка таблицы, открывающая свою страницу нажатием в любое место.
 *
 * Ссылка на сам пост остаётся отдельной ссылкой внутри строки и уводит на
 * площадку: нажатие по ней не должно открывать нашу страницу, поэтому такие
 * нажатия сюда не доходят.
 *
 * Настоящая ссылка внутри строки никуда не делась — она и остаётся тем, что
 * видит клавиатура и читалка экрана. Эта обёртка лишь добавляет второй, более
 * крупный способ нажать то же самое: строка сама по себе ссылкой не является,
 * и подменять ею настоящую нельзя.
 */
export function RowLink({ href, children, className, ...rest }: {
  href: string; children: ReactNode; className?: string;
} & Record<string, unknown>) {
  const router = useRouter();
  return (
    <TableRow
      {...rest}
      className={className}
      onClick={(event) => {
        // Нажатие по ссылке, кнопке или выделенному тексту остаётся своим.
        const target = event.target as HTMLElement;
        if (target.closest("a,button,input,select,label")) return;
        if (window.getSelection()?.toString()) return;
        router.push(href);
      }}
    >
      {children}
    </TableRow>
  );
}
