"use client";

import { useEffect, useSyncExternalStore, type ReactNode } from "react";
import { beginNavigation, endNavigation, NAVIGATED, navigationLeft, readNavigation, subscribeNavigation, watchHistory } from "@/lib/navigation-pending";
import { LoadingState } from "@/components/loading-state";

/** Переход, который не завершился за это время, скорее всего не состоялся —
 *  например, ссылку открыли в новой вкладке. Заготовка не должна висеть. */
const GIVE_UP_MS = 12_000;

/**
 * Показывает заготовку вместо того куска страницы, который меняется.
 *
 * Обёртка ставится не на всю страницу, а вокруг изменчивой части: при смене
 * фильтра заголовок и сама строка фильтров остаются на месте и продолжают
 * отвечать на нажатия, а серым мигает только список. Содержимое остаётся
 * серверным — обёртка лишь подменяет его на время клиентского перехода, и
 * при выключенных скриптах не делает ничего.
 */
export function NavigationBoundary({ children, fallback }: { children: ReactNode; fallback?: ReactNode }) {
  const pending = useSyncExternalStore(subscribeNavigation, readNavigation, () => false);

  // Признак прибытия — смена адреса. Слот children роутер отдаёт одним и тем
  // же элементом, так что по нему обновление не поймать, а хук параметров
  // запроса потребовал бы обернуть обёртку в Suspense — и её серверный
  // запасной вариант нарисовал бы ту же страницу второй раз.
  useEffect(() => { watchHistory(); }, []);

  useEffect(() => {
    if (!pending) return;
    const check = () => { if (navigationLeft()) endNavigation(); };
    // Опрос остаётся страховкой на случай перехода без записи в историю.
    const ticker = setInterval(check, 50);
    const timer = setTimeout(endNavigation, GIVE_UP_MS);
    window.addEventListener(NAVIGATED, check);
    window.addEventListener("popstate", check);
    return () => {
      clearInterval(ticker); clearTimeout(timer);
      window.removeEventListener(NAVIGATED, check);
      window.removeEventListener("popstate", check);
    };
  }, [pending]);

  return pending ? <>{fallback ?? <LoadingState />}</> : <>{children}</>;
}

/** Нажатие, которое действительно уводит на другой адрес в этой же вкладке. */
export function navigationClick(event: React.MouseEvent<HTMLAnchorElement>, href: string) {
  if (event.defaultPrevented || event.button !== 0) return;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const target = event.currentTarget.target;
  if (target && target !== "_self") return;
  // Якорь на той же странице и внешний адрес переходом не считаются.
  if (href.startsWith("#") || /^[a-z]+:/i.test(href)) return;
  if (href === `${location.pathname}${location.search}`) return;
  beginNavigation();
}
