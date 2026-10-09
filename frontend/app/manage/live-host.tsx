"use client";

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { SystemLive, SystemLivePoint } from "@/lib/catalog-api";

/** Три часа — столько держит буфер API; больше в браузере не копим. */
const HORIZON_MS = 3 * 3600_000;
const FALLBACK_INTERVAL_MS = 5_000;

export type LiveMeta = Omit<SystemLive, "points">;
export type LiveHost = { meta: LiveMeta | null; points: SystemLivePoint[]; state: "loading" | "live" | "unavailable" };

const LiveHostContext = createContext<LiveHost>({ meta: null, points: [], state: "loading" });

/**
 * Живой мониторинг вкладки «Система». Первый запрос забирает весь буфер API
 * (до трёх часов точек), дальше раз в шаг снимка — только точки новее
 * последней (since), обычно одну. Скрытая вкладка браузера не опрашивает
 * сервер; при возвращении данные дочитываются сразу.
 */
export function LiveHostProvider({ children }: { children: ReactNode }) {
  const [live, setLive] = useState<LiveHost>({ meta: null, points: [], state: "loading" });
  const last = useRef<string | null>(null);

  useEffect(() => {
    let timer: number | undefined;
    let stopped = false;
    let controller: AbortController | null = null;
    let interval = FALLBACK_INTERVAL_MS;

    const poll = async () => {
      window.clearTimeout(timer);
      if (stopped) return;
      if (document.visibilityState === "visible") {
        controller?.abort();
        controller = new AbortController();
        try {
          const query = last.current ? `?since=${encodeURIComponent(last.current)}` : "";
          const response = await fetch(`/api/v1/admin/system/live${query}`, {
            cache: "no-store", credentials: "same-origin", signal: controller.signal, headers: { Accept: "application/json" },
          });
          if (!response.ok) throw new Error(String(response.status));
          const body = await response.json() as SystemLive;
          const { points: fresh, ...meta } = body;
          if (meta.intervalSeconds) interval = Math.max(2_000, meta.intervalSeconds * 1000);
          if (fresh.length) last.current = fresh[fresh.length - 1].at;
          setLive((previous) => {
            const merged = fresh.length ? [...previous.points, ...fresh] : previous.points;
            const edge = Date.now() - HORIZON_MS;
            const start = merged.findIndex((point) => Date.parse(point.at) >= edge);
            return { meta, points: start > 0 ? merged.slice(start) : merged, state: meta.intervalSeconds ? "live" : "unavailable" };
          });
        } catch (error) {
          if ((error as Error).name === "AbortError") return;
          setLive((previous) => ({ ...previous, state: previous.points.length ? previous.state : "unavailable" }));
        }
      }
      timer = window.setTimeout(poll, interval);
    };
    const onVisible = () => { if (document.visibilityState === "visible") void poll(); };
    void poll();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  return <LiveHostContext.Provider value={live}>{children}</LiveHostContext.Provider>;
}

export function useLiveHost() {
  return useContext(LiveHostContext);
}
