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
  const key = ids.join(",");

  useEffect(() => {
    let alive = true;
    for (const id of key ? key.split(",") : []) {
      load(id, period).then(
        (data) => { if (alive) setResults((current) => new Map(current).set(id, { status: "ready", data })); },
        () => { if (alive) setResults((current) => new Map(current).set(id, { status: "error" })); },
      );
    }
    return () => { alive = false; };
  }, [key, period, attempt]);

  const states = useMemo(() => new Map(ids.map((id) => [id, results.get(id) ?? LOADING])), [ids, results]);
  const retry = useCallback(() => {
    setResults((current) => new Map([...current].filter(([, state]) => state.status !== "error")));
    setAttempt((value) => value + 1);
  }, []);
  return { states, retry };
}
