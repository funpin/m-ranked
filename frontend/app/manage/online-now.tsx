"use client";

import { LiveNumber } from "./live-number";

/** «Сейчас на сайте»: число обновляется вместе со страницей (LiveRefresh). */
export function OnlineNow({ online }: { online: number }) {
  return (
    <span data-testid="online-now" aria-live="polite" className="inline-flex items-center gap-2">
      <span className="relative flex size-2.5" aria-hidden="true">
        {online > 0 ? <span className="bg-success absolute inline-flex size-full animate-ping rounded-full opacity-60 motion-reduce:hidden" /> : null}
        <span className={`relative inline-flex size-2.5 rounded-full ${online > 0 ? "bg-success" : "bg-muted-foreground/40"}`} />
      </span>
      <LiveNumber value={online} className="font-heading text-3xl font-semibold" />
    </span>
  );
}
