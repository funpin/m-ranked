"use client";

import { useEffect, useSyncExternalStore, type ReactNode } from "react";
import { beginNavigation, endNavigation, NAVIGATED, navigationLeft, navigationTarget, readNavigation, subscribeNavigation, watchHistory } from "@/lib/navigation-pending";
import { skeletonFor } from "@/components/skeletons";
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
/** Переход ещё идёт?
 *
 *  Хранилище гасится эффектом, а он выполняется на кадр позже фиксации нового
 *  адреса. Этого кадра хватало, чтобы заготовка мелькнула поверх уже готовой
 *  страницы, поэтому адрес сверяется прямо при отрисовке; хранилище поправит
 *  себя следом.
 */
function stillPending(pending: boolean) {
  return pending && !(typeof location !== "undefined" && navigationLeft());
}

export function NavigationBoundary({ children, fallback }: { children: ReactNode; fallback?: ReactNode }) {
  const pending = useSyncExternalStore(subscribeNavigation, readNavigation, () => false);

  // Слежение за завершением перехода живёт в обёртке маршрута: эта обёртка
  // стоит внутри страницы и на межмаршрутном переходе размонтируется вместе
  // с ней — тогда завершать переход стало бы некому.
  // Межмаршрутный переход берёт на себя обёртка в макете: там подменяется
  // всё содержимое, включая заголовок и фильтры прежней страницы.
  if (!stillPending(pending) || crossRoute(navigationTarget())) return <>{children}</>;
  return <>{fallback ?? <LoadingState />}</>;
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
  beginNavigation(href);
}

/** Заготовка целого маршрута.
 *
 * Стоит в макете и срабатывает только при уходе на другой маршрут: тогда от
 * прежней страницы не должно остаться ни заголовка, ни фильтров — их место
 * занимает заготовка той страницы, куда идём. Переходы внутри маршрута —
 * смена фильтра, соседний пост — этой обёртки не касаются: там подменяется
 * только изменчивая часть, которую обозначила сама страница.
 */
export function RouteBoundary({ children }: { children: ReactNode }) {
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

  if (!stillPending(pending)) return <>{children}</>;
  const destination = crossRoute(navigationTarget()) ? skeletonFor(navigationTarget()) : null;
  return destination ? <>{destination}</> : <>{children}</>;
}

/** Ведёт ли переход на другой маршрут, а не в другое состояние текущего. */
function crossRoute(href: string) {
  if (!href || typeof location === "undefined") return false;
  const target = href.split("?")[0] ?? "";
  return routeOf(target) !== routeOf(location.pathname);
}

function routeOf(path: string) {
  const [, first = "", second = ""] = path.split("/");
  // Детальные маршруты различаются первым сегментом, списочные — сами собой.
  return first ? `${first}${second ? "/*" : ""}` : "/";
}
