"use client";

import { useEffect, useSyncExternalStore } from "react";
import { Contrast } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  applyTheme,
  readThemePreference,
  resolveTheme,
  themeLabel,
} from "@/lib/theme";

/**
 * One press, one switch.
 *
 * The control used to open a three-item menu, which made changing the theme a
 * two-step interaction for the one thing people actually do — go the other
 * way. The third state is still reachable: until someone presses the button,
 * nothing is stored and the operating system keeps control.
 */
export function ThemeToggle() {
  const resolved = useSyncExternalStore(
    subscribe,
    () => (document.documentElement.dataset.theme === "light" ? "light" : "dark"),
    () => "dark" as const,
  );
  const preference = useSyncExternalStore(subscribe, readThemePreference, () => "system" as const);

  // While nothing is stored, the operating system keeps control. The stored
  // value is re-read inside the handler rather than taken from the render:
  // during hydration this component still holds the server's value, and a
  // stale one here would overwrite a choice the inline script already applied.
  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: light)");
    const follow = () => { document.documentElement.dataset.theme = resolveTheme(readThemePreference()); };
    // Тему на первом кадре уже поставил инлайновый скрипт, а нажатие ставит её
    // само. Повторять при монтировании нельзя: компонент приезжает позже
    // остальной страницы и затирал бы атрибут, выставленный кем-то ещё.
    query.addEventListener("change", follow);
    return () => query.removeEventListener("change", follow);
  }, [preference]);

  const next = resolved === "dark" ? "light" : "dark";
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={`${themeLabel(preference)}. Переключить на ${next === "dark" ? "тёмную" : "светлую"}`}
      title={next === "dark" ? "Тёмная тема" : "Светлая тема"}
      onClick={() => applyTheme(next)}
    >
      {/* Один значок на оба состояния, как в системе, откуда взят стиль:
          кнопка обозначает саму тему, а не текущее её положение. */}
      <Contrast className={cn("size-[1.15rem] transition-transform", resolved === "light" && "-scale-x-100")} aria-hidden="true" />
    </Button>
  );
}

/** The attribute on <html> and the stored preference are the two things that
 *  can change the control, so the store watches both. */
function subscribe(notify: () => void) {
  const observer = new MutationObserver(notify);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  window.addEventListener("storage", notify);
  return () => { observer.disconnect(); window.removeEventListener("storage", notify); };
}
