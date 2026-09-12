"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  readThemePreference,
  subscribeTheme,
  systemTheme,
  themeLabel,
} from "@/lib/theme";

// Loaded on first interaction. Keeping the floating-menu primitive out of the
// root layout's shared chunk saves about 48 KiB gzip on every route.
const ThemeMenu = dynamic(() => import("@/components/theme-menu").then((module) => module.ThemeMenu), { ssr: false });

export function ThemeToggle() {
  const resolved = useSyncExternalStore(
    subscribeTheme,
    () => (document.documentElement.dataset.theme === "light" ? "light" : "dark"),
    () => "dark" as const,
  );
  const preference = useSyncExternalStore(subscribeTheme, readThemePreference, () => "dark" as const);
  // "none" until the pointer arrives or the button is pressed; a press also
  // opens the menu as soon as it arrives, so one click is still one click.
  const [activation, setActivation] = useState<"none" | "preload" | "open">("none");

  // While the preference is "system", the operating system keeps control.
  useEffect(() => {
    if (preference !== "system") return;
    const query = window.matchMedia("(prefers-color-scheme: light)");
    const follow = () => { document.documentElement.dataset.theme = systemTheme(); };
    follow();
    query.addEventListener("change", follow);
    return () => query.removeEventListener("change", follow);
  }, [preference]);

  const label = themeLabel(preference);
  const icon = preference === "system"
    ? <Monitor className="size-[1.15rem]" aria-hidden="true" />
    : resolved === "dark"
      ? <Moon className="size-[1.15rem]" aria-hidden="true" />
      : <Sun className="size-[1.15rem]" aria-hidden="true" />;

  // Tabbing to the button must not swap it out from under the focus, so only
  // a pointer or an actual press loads the menu.
  if (activation === "none") {
    return (
      <Button
        variant="ghost"
        size="icon"
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        onPointerEnter={() => setActivation("preload")}
        onClick={() => setActivation("open")}
      >
        {icon}
      </Button>
    );
  }

  return <ThemeMenu preference={preference} resolved={resolved} label={label} defaultOpen={activation === "open"} />;
}
