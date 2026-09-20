import Link from "@/components/native-link";
import { queryHref } from "@/lib/params";
import type { Platform } from "@/lib/types";
import logo from "../assets/logo.png";
import { NAV_LINKS } from "@/lib/nav-links";
import { HeaderUtilityActions } from "@/components/header-utility-actions";

/**
 * Серверная половина шапки.
 *
 * Живая шапка знает текущий маршрут и подсвечивает активный пункт, а для этого
 * ей нужен клиент. Пока он не приехал — или не приедет вовсе, если скрипты
 * выключены, — меню должно быть на месте и работать: те же адреса, тот же
 * размер, чтобы подмена не дёргала раскладку.
 */
export function SiteHeaderFallback({ platform }: { platform: Platform }) {
  return (
    <nav
      aria-label="Основная навигация"
      className="bg-background sticky top-0 z-[200] flex h-14 items-center gap-6 border-b px-[max(1.25rem,calc((100%-1320px)/2))]"
    >
      <Link
        data-testid="brand"
        className="text-foreground flex shrink-0 items-center gap-2 text-base font-bold tracking-tight no-underline"
        href={queryHref("/", { platform })}
        aria-label="m-ranked — обзор"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={logo.src} alt="" width={28} height={28} className="size-7 rounded-md object-cover" fetchPriority="high" decoding="async" />
        <strong className="font-heading font-bold">m-ranked</strong>
      </Link>
      <div data-testid="main-nav" className="mr-auto flex items-center gap-1 max-[780px]:hidden">
        {NAV_LINKS.map((link) => (
          <Link
            key={link.href}
            href={queryHref(link.href, { platform })}
            className="text-muted-foreground rounded-md px-3 py-1.5 text-[0.875rem] font-medium no-underline transition-colors"
          >
            {link.label}
          </Link>
        ))}
      </div>
      <HeaderUtilityActions />
    </nav>
  );
}
