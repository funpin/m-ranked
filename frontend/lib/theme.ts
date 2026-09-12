export type ResolvedTheme = "dark" | "light";
/** "system" follows the operating system; the other two are explicit choices. */
export type ThemePreference = ResolvedTheme | "system";

export const THEME_STORAGE_KEY = "m-ranked-theme";

export function readThemePreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // A blocked storage API must not break the control.
  }
  // Anyone who never chose keeps the dark default the product has always had.
  return "dark";
}

export function systemTheme(): ResolvedTheme {
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  return preference === "system" ? systemTheme() : preference;
}

/**
 * The attribute on <html> stays the single source of truth: the inline script
 * in the layout sets it before first paint, and everything that needs to know
 * the theme reads it from there.
 */
export function applyTheme(preference: ThemePreference) {
  const root = document.documentElement;
  // A theme swap must not animate. Blended mid-transition colours look wrong
  // and dip below the contrast floor while they are running.
  root.dataset.themeSwitching = "";
  root.dataset.theme = resolveTheme(preference);
  requestAnimationFrame(() => requestAnimationFrame(() => { delete root.dataset.themeSwitching; }));
  try {
    localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // A blocked storage API must not prevent the visible change.
  }
}

export function subscribeTheme(notify: () => void) {
  const observer = new MutationObserver(notify);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  window.addEventListener("storage", notify);
  return () => { observer.disconnect(); window.removeEventListener("storage", notify); };
}

export function themeLabel(preference: ThemePreference) {
  return preference === "system" ? "Тема: системная"
    : preference === "dark" ? "Тема: тёмная" : "Тема: светлая";
}
