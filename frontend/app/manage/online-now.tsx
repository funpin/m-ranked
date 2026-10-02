"use client";

import { useEffect, useState } from "react";

const REFRESH_MS = 30_000;

/** «Сейчас на сайте»: обновляется раз в полминуты, пока вкладка видна. */
export function OnlineNow({ initial }: { initial: number }) {
  const [online, setOnline] = useState(initial);
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const response = await fetch("/api/v1/admin/visitors?range=week", { cache: "no-store", credentials: "same-origin" });
        if (response.ok && active) setOnline((await response.json()).online);
      } catch { /* сеть пропала: оставляем прежнее число до следующей попытки */ }
    };
    const timer = window.setInterval(refresh, REFRESH_MS);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  return (
    <span data-testid="online-now" aria-live="polite" className="inline-flex items-center gap-2">
      <span className="relative flex size-2.5" aria-hidden="true">
        {online > 0 ? <span className="bg-success absolute inline-flex size-full animate-ping rounded-full opacity-60 motion-reduce:hidden" /> : null}
        <span className={`relative inline-flex size-2.5 rounded-full ${online > 0 ? "bg-success" : "bg-muted-foreground/40"}`} />
      </span>
      <span className="font-heading text-3xl font-semibold tabular-nums">{online}</span>
    </span>
  );
}
