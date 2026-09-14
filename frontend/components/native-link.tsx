"use client";

import NextLink from "next/link";
import type { AnchorHTMLAttributes, MouseEvent } from "react";
import { navigationClick } from "@/components/navigation-boundary";

type NativeLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string;
  prefetch?: boolean;
  scroll?: boolean;
};

/**
 * Переход без перезагрузки, но без единого спекулятивного запроса.
 *
 * Раньше здесь стоял обычный <a>: опасались, что предзагрузка соседних
 * маршрутов начнёт веерно дёргать API, у которого один процесс и жёсткий
 * потолок памяти. Опасение касалось именно предзагрузки — клиентский переход
 * ходит на сервер ровно один раз и ровно тогда, когда по ссылке нажали.
 * Поэтому ссылка стала клиентской, а предзагрузка выключена по умолчанию:
 * в этой версии Next `prefetch={false}` означает «никогда» — ни при попадании
 * в область видимости, ни при наведении.
 */
export default function NativeLink({ href, prefetch = false, scroll, onClick, ...props }: NativeLinkProps) {
  return <NextLink href={href} prefetch={prefetch} scroll={scroll} {...props}
    onClick={(event: MouseEvent<HTMLAnchorElement>) => { onClick?.(event); navigationClick(event, href); }} />;
}
