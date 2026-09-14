"use client";

import Link from "@/components/native-link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Menu, X } from "lucide-react";
import { normalizePlatform, queryHref } from "@/lib/params";
import type { Platform } from "@/lib/types";
import logo from "../assets/logo.png";
import { ThemeToggle } from "./theme-toggle";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Логотип GitHub — фирменный знак, в наборе иконок интерфейса его нет. */
function GithubMark() {
  return (
    <svg viewBox="0 0 16 16" className="size-[1.15rem] fill-current" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  );
}

const links = [
  { href: "/", label: "Обзор" },
  { href: "/rating", label: "Рейтинг" },
  { href: "/compare", label: "Сравнение" },
  { href: "/export/snapshots.csv", label: "Экспорт CSV" },
  { href: "/manage", label: "Управление" },
];

function subscribePlatform(notify: () => void) {
  const observer = new MutationObserver(notify);
  const main = document.getElementById("main-content");
  if(main) observer.observe(main,{childList:true,subtree:true,attributes:true,attributeFilter:["data-active-platform"]});
  return () => observer.disconnect();
}

export function SiteHeader({initialPlatform="telegram"}:{initialPlatform?:Platform}) {
  const pathname = usePathname();
  const search = useSearchParams();
  const detailPlatform = useSyncExternalStore(subscribePlatform, () => normalizePlatform(document.querySelector<HTMLElement>("main [data-active-platform]")?.dataset.activePlatform, initialPlatform), () => initialPlatform);
  const platform = /^\/(accounts|publications)\//.test(pathname) ? detailPlatform : normalizePlatform(search.getAll("platform"), pathname.startsWith("/institutions/") ? "all" : /^\/(platform-posts|platform-accounts)\//.test(pathname) ? detailPlatform : "telegram");
  const [menuOpen, setMenuOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const navigation = useRef<HTMLDivElement>(null);
  const routeKey = `${pathname}?${search}`;
  const [openedAt, setOpenedAt] = useState(routeKey);
  const visible = menuOpen && openedAt === routeKey;

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 781px)");
    function closeDesktop() {
      if (desktop.matches) {
        const focusedLink = navigation.current?.contains(document.activeElement);
        setMenuOpen(false);
        if (focusedLink) navigation.current?.querySelector<HTMLAnchorElement>("a")?.focus();
      }
    }
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") { setMenuOpen(false); toggle.current?.focus(); }
    }
    desktop.addEventListener("change", closeDesktop);
    document.addEventListener("keydown", escape);
    return () => {
      desktop.removeEventListener("change", closeDesktop);
      document.removeEventListener("keydown", escape);
    };
  }, []);

  return (
    <nav
      aria-label="Основная навигация"
      // Шапка непрозрачная: сквозь полупрозрачную просвечивали карточки, и
      // строка меню читалась как случайное наложение поверх содержимого.
      className="bg-background sticky top-0 z-[200] flex h-14 items-center gap-6 border-b px-[max(1.25rem,calc((100%-1320px)/2))]"
    >
      <Link
        data-testid="brand"
        className="text-foreground mr-auto flex shrink-0 items-center gap-2 text-base font-bold tracking-tight no-underline"
        href={queryHref("/", { platform })}
        aria-label="m-ranked — обзор"
        prefetch={false}
        onClick={() => setMenuOpen(false)}
      >
        {/* The fixed local logo needs no image optimizer or browser image runtime. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={logo.src} alt="" width={28} height={28} className="size-7 rounded-md object-cover" fetchPriority="high" decoding="async" />
        <strong className="font-heading font-bold">m-ranked</strong>
      </Link>

      <div
        ref={navigation}
        id="primary-navigation"
        data-testid="main-nav"
        className={cn(
          "max-[780px]:bg-popover max-[780px]:absolute max-[780px]:top-full max-[780px]:right-4 max-[780px]:z-50",
          "max-[780px]:min-w-52 max-[780px]:flex-col max-[780px]:items-stretch max-[780px]:gap-1",
          "max-[780px]:rounded-lg max-[780px]:border max-[780px]:p-2 max-[780px]:shadow-lg",
          "flex items-center gap-1",
          visible
            ? "max-[780px]:animate-in max-[780px]:fade-in-0 max-[780px]:zoom-in-95 max-[780px]:flex"
            : "max-[780px]:hidden",
        )}
      >
        {links.map((link) => {
          const active = link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={queryHref(link.href, { platform })}
              aria-current={active ? "page" : undefined}
              prefetch={false}
              onClick={() => { setMenuOpen(false); if (visible) toggle.current?.focus(); }}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium no-underline transition-colors",
                "hover:bg-accent hover:text-accent-foreground hover:no-underline",
                "focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none",
                active ? "text-foreground" : "text-muted-foreground",
              )}
            >
              {link.label}
            </Link>
          );
        })}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          render={
            <a href="https://github.com/funpin/m-ranked" target="_blank" rel="noopener noreferrer" aria-label="Исходный код на GitHub" title="Исходный код на GitHub">
              <GithubMark />
            </a>
          }
        />
        <ThemeToggle />
        <Button
          data-testid="menu-toggle"
          variant="ghost"
          size="icon"
          className="min-[781px]:hidden"
          ref={toggle}
          type="button"
          aria-label={visible ? "Закрыть меню" : "Открыть меню"}
          aria-expanded={visible}
          aria-controls="primary-navigation"
          onClick={() => { setOpenedAt(routeKey); setMenuOpen(!visible); }}
        >
          {visible ? <X className="size-[1.15rem]" aria-hidden="true" /> : <Menu className="size-[1.15rem]" aria-hidden="true" />}
        </Button>
      </div>
    </nav>
  );
}
