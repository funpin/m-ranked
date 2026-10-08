"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { DashboardPeriod } from "@/lib/compare-dashboard";
import { fetchInstitutionTiming, type InstitutionTiming } from "@/lib/compare-timing";

export type TimingState = { status: "loading" } | { status: "error" } | { status: "ready"; data: InstitutionTiming };
const LOADING: TimingState = { status: "loading" };

// Ответы живут, пока открыта страница: снятое и снова выделенное не грузится
// заново. Ошибка из кэша удаляется, чтобы «Повторить» действительно повторял.
const cache = new Map<string, Promise<InstitutionTiming>>();
const CACHE_LIMIT = 64;

function load(id: string, period: DashboardPeriod): Promise<InstitutionTiming> {
  const key = `${period}|${id}`;
  let pending = cache.get(key);
  if (!pending) {
    pending = fetchInstitutionTiming(id, period);
    pending.catch(() => cache.delete(key));
    cache.set(key, pending);
    if (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value!);
  }
  return pending;
}

/** Время и форматы выделенных вузов: по запросу на вуз, параллельно. Вуз
 *  без ответа — «загружается». */
export function useInstitutionTiming(ids: readonly string[], period: DashboardPeriod) {
  const [results, setResults] = useState<ReadonlyMap<string, TimingState>>(new Map());
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    // Уже пришедший ответ не перезаписывается: иначе каждое новое выделение
    // заново перерисовывало бы всю панель ради тех же данных.
    const settle = (id: string, next: TimingState) => {
      if (alive) setResults((current) => current.get(id)?.status === "ready" ? current : new Map(current).set(id, next));
    };
    for (const id of ids) load(id, period).then((data) => settle(id, { status: "ready", data }), () => settle(id, { status: "error" }));
    return () => { alive = false; };
  }, [ids, period, attempt]);

  const states = useMemo(() => new Map(ids.map((id) => [id, results.get(id) ?? LOADING])), [ids, results]);
  const retry = useCallback(() => {
    setResults((current) => new Map([...current].filter(([, state]) => state.status !== "error")));
    setAttempt((value) => value + 1);
  }, []);
  return { states, retry };
}
