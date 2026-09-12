"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import logo from "../../app/web/static/logo.png";
import { ThemeToggle } from "./theme-toggle";

const links = [
  { href: "/", label: "Обзор" },
  { href: "/rating", label: "Рейтинг" },
  { href: "/compare", label: "Сравнение" },
  { href: "/export/snapshots.csv", label: "Экспорт CSV" },
  { href: "/manage", label: "Управление" },
];

export function SiteHeader() {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  return (
    <header className="site-header">
      <div className="nav-shell">
        <Link className="brand" href="/" aria-label="m-ranked — обзор">
          <span className="brand-mark" aria-hidden="true">
            <Image src={logo} alt="" width={42} height={42} priority sizes="(max-width: 780px) 36px, 42px" />
          </span>
          <strong className="brand-word"><span>m</span>-ranked</strong>
        </Link>
        <nav id="primary-navigation" className={`main-nav${menuOpen ? " is-open" : ""}`} aria-label="Основная навигация">
          {links.map((link) => {
            const active = link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
            return (
              <Link key={link.href} href={link.href} aria-current={active ? "page" : undefined} prefetch={false}>
                {link.label}
              </Link>
            );
          })}
        </nav>
        <div className="nav-actions">
          <ThemeToggle />
          <button
            className="menu-toggle"
            type="button"
            aria-label={menuOpen ? "Закрыть меню" : "Открыть меню"}
            aria-expanded={menuOpen}
            aria-controls="primary-navigation"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <span className="menu-toggle-bars" aria-hidden="true"><i /><i /><i /></span>
          </button>
        </div>
      </div>
    </header>
  );
}
