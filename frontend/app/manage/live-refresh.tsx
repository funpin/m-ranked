"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";

const time = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Moscow" });

/** Пользователь сейчас что-то делает на странице: обновление подождёт. */
function busy() {
  if (document.querySelector('[role="dialog"], [role="alertdialog"]')) return true;
  const active = document.activeElement;
  return active instanceof HTMLElement && active.matches("input:not([type=hidden]):not([type=radio]):not([type=checkbox]), textarea, select, [contenteditable]");
}

/**
 * Живое обновление панели: раз в intervalMs страница заново запрашивает свои
 * данные у сервера (router.refresh) — числа, проверки, графики и таблица
 * меняются на месте, без перезагрузки; открытые окна, введённый текст и
 * прокрутка сохраняются. Пока вкладка браузера скрыта, открыто окно или идёт
 * ввод, обновление пропускается; при возвращении на вкладку — сразу.
 */
export function LiveRefresh({ intervalMs }: { intervalMs: number }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const last = useRef(0);

  useEffect(() => {
    const refresh = (force = false) => {
      if (document.visibilityState !== "visible" || busy()) return;
      // Возврат на вкладку обновляет сразу, но не чаще раза в две секунды.
      if (Date.now() - last.current < (force ? 2000 : intervalMs * 0.8)) return;
      last.current = Date.now();
      startTransition(() => router.refresh());
      setUpdatedAt(Date.now());
    };
    last.current = Date.now();
    const timer = window.setInterval(() => refresh(), intervalMs);
    const onVisible = () => { if (document.visibilityState === "visible") refresh(true); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [intervalMs, router]);

  return (
    <span data-testid="live-refresh" className="text-muted-foreground inline-flex items-center gap-2 text-xs" title={`Данные обновляются автоматически каждые ${Math.round(intervalMs / 1000)} с`}>
      <span className="relative flex size-2" aria-hidden="true">
        <span className={cn("bg-success absolute inline-flex size-full rounded-full opacity-60 motion-reduce:hidden", pending ? "animate-ping" : "animate-pulse")} />
        <span className="bg-success relative inline-flex size-2 rounded-full" />
      </span>
      <span>{pending ? "Обновляется…" : updatedAt ? `Обновлено ${time.format(updatedAt)}` : "Обновляется автоматически"}</span>
    </span>
  );
}
