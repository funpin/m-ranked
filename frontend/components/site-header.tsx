"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { normalizePlatform, queryHref } from "@/lib/params";
import type { Platform } from "@/lib/types";
import logo from "../assets/logo.png";
import { ThemeToggle } from "./theme-toggle";

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
    <nav className="site-nav" aria-label="Основная навигация">
        <Link className="brand" href={queryHref("/", { platform })} aria-label="m-ranked — обзор" prefetch={false} onClick={() => setMenuOpen(false)}>
          {/* The fixed local logo needs no image optimizer or browser image runtime. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={logo.src} alt="" width={42} height={42} fetchPriority="high" decoding="async" />
          <strong className="brand-word"><span>m</span>-ranked</strong>
        </Link>
        <div ref={navigation} id="primary-navigation" className={`nav-links main-nav${visible ? " is-open" : ""}`}>
          {links.map((link) => {
            const active = link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
            return (
              <Link key={link.href} href={queryHref(link.href, { platform })} aria-current={active ? "page" : undefined} prefetch={false} onClick={() => { setMenuOpen(false); if (visible) toggle.current?.focus(); }}>
                {link.label}
              </Link>
            );
          })}
        </div>
        <div className="nav-actions">
          <ThemeToggle />
          <button
            className="menu-toggle"
            ref={toggle}
            type="button"
            aria-label={visible ? "Закрыть меню" : "Открыть меню"}
            aria-expanded={visible}
            aria-controls="primary-navigation"
            onClick={() => { setOpenedAt(routeKey); setMenuOpen(!visible); }}
          >
            <span className="menu-toggle-bars" aria-hidden="true"><i /><i /><i /></span>
          </button>
        </div>
    </nav>
  );
}
