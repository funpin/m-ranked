"use client";

import { useSyncExternalStore } from "react";

type Theme = "dark" | "light";

function getTheme(): Theme { return document.documentElement.dataset.theme === "light" ? "light" : "dark"; }
function subscribe(notify: () => void) {
  const observer = new MutationObserver(notify);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, getTheme, () => "dark" as const);

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("m-ranked-theme", next);
    } catch {
      // A blocked storage API must not prevent the visible preference change.
    }

  }

  const nextLabel = theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему";
  return (
    <button className="theme-toggle" type="button" onClick={toggleTheme} aria-label={nextLabel}>
      <span className="theme-toggle-icon" aria-hidden="true">{theme === "dark" ? "☾" : "☀"}</span>
      <span className="theme-toggle-label">{theme === "dark" ? "Тёмная" : "Светлая"}</span>
    </button>
  );
}
