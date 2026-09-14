"use client";

import { useSyncExternalStore } from "react";

/**
 * Какой день недели выбран на графике площадки.
 *
 * График и таблица публикаций стоят в разных поддеревьях и не имеют общего
 * родителя-клиента: таблица рисуется на сервере и на клиент приезжает готовой
 * разметкой. Общее состояние живёт здесь, чтобы не тащить всю таблицу в
 * клиентский код ради одной подсветки.
 */
let focused: string | null = null;
const listeners = new Set<() => void>();

function notify() {
  for (const listener of listeners) listener();
}

/** Выбирает день или снимает выбор повторным нажатием по той же точке. */
export function toggleFocusedDay(day: string | null) {
  focused = focused === day ? null : day;
  notify();
}

export function clearFocusedDay() {
  if (focused === null) return;
  focused = null;
  notify();
}

/** Выбранный день. Экспортирован ради тестов и снимка для useSyncExternalStore. */
export function focusedDay(): string | null {
  return focused;
}

export function subscribeToFocusedDay(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useFocusedDay(): string | null {
  // На сервере дня нет: выбор делается нажатием и до гидратации не существует.
  return useSyncExternalStore(subscribeToFocusedDay, focusedDay, () => null);
}
