"use client";

import { useEffect, useState } from "react";

type Theme = "dark" | "light";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    const current = document.documentElement.dataset.theme === "light" ? "light" : "dark";
    setTheme(current);
  }, []);

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("m-ranked-theme", next);
    } catch {
      // A blocked storage API must not prevent the visible preference change.
    }
    setTheme(next);
  }

  const nextLabel = theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему";
  return (
    <button className="theme-toggle" type="button" onClick={toggleTheme} aria-label={nextLabel}>
      <span aria-hidden="true">{theme === "dark" ? "☾" : "☀"}</span>
      <span className="theme-label">{theme === "dark" ? "Тёмная" : "Светлая"}</span>
    </button>
  );
}
