"use client";

/**
 * Одно на всё приложение состояние «переход начался».
 *
 * Раньше мгновенный скелетон давали файлы loading.tsx: Next оборачивал каждый
 * такой маршрут в границу Suspense. Побочный эффект был серьёзнее пользы —
 * при выключенных скриптах содержимое оставалось лежать в <template>, а на
 * экране навсегда замирал скелетон. Теперь скелетон рисует сам клиент: без
 * скриптов страница приходит целиком, со скриптами переход показывает
 * заготовку ровно на время ожидания.
 */
let pending = false;
let startedAt = "";
let target = "";
const listeners = new Set<() => void>();

function publish() { for (const notify of listeners) notify(); }

export function beginNavigation(href = "") {
  if (pending) return;
  pending = true;
  startedAt = location.href;
  target = href;
  publish();
}

/** Куда уходим. Заготовку выбирает страница назначения, а не та, с которой
 *  уходят: показывать при переходе на рейтинг сетку карточек обзора значит
 *  обещать не то, что появится. */
export function navigationTarget() { return target; }

/** Адрес, с которого начали. Роутер меняет его только после того, как новое
 *  содержимое готово, поэтому расхождение и означает «приехали». */
export function navigationLeft() { return pending && location.href !== startedAt; }

/**
 * Роутер объявляет о прибытии единственным способом — записью в историю.
 * Событие об этом браузер не шлёт, поэтому запись оборачивается один раз, и
 * заготовка исчезает в тот же миг, а не через такт опроса.
 */
export const NAVIGATED = "mranked:navigated";
let patched = false;
export function watchHistory() {
  if (patched || typeof history === "undefined") return;
  patched = true;
  for (const name of ["pushState", "replaceState"] as const) {
    const original = history[name];
    history[name] = function patchedHistory(this: History, ...args: Parameters<History["pushState"]>) {
      const result = original.apply(this, args);
      window.dispatchEvent(new Event(NAVIGATED));
      return result;
    };
  }
}

export function endNavigation() {
  if (!pending) return;
  pending = false;
  target = "";
  publish();
}

export function subscribeNavigation(notify: () => void) {
  listeners.add(notify);
  return () => { listeners.delete(notify); };
}

export function readNavigation() { return pending; }
