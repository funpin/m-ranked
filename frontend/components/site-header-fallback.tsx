import Link from "@/components/native-link";
import { queryHref } from "@/lib/params";
import type { Platform } from "@/lib/types";
import { MANAGE_LINK, NAV_LINKS } from "@/lib/nav-links";
import { HeaderUtilityActions } from "@/components/header-utility-actions";
import { BrandLogo } from "@/components/brand-logo";

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
      className="site-header-glass sticky top-0 z-[200] h-14 border-b"
    >
      <div data-testid="header-inner" className="safe-page-inset relative mx-auto flex h-full w-full max-w-[1400px] items-center gap-6">
        <Link
          data-testid="brand"
          className="flex shrink-0 items-center no-underline"
          href={queryHref("/", { platform })}
          aria-label="m-ranked — обзор"
        >
          <BrandLogo />
        </Link>
        <div data-testid="main-nav" className="mr-auto flex items-center gap-1 max-[780px]:hidden">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={queryHref(link.href, { platform })}
              className={`${"utility" in link ? "min-[781px]:hidden " : ""}text-muted-foreground rounded-md px-3 py-1.5 text-[0.875rem] font-medium no-underline transition-colors`}
            >
              {link.label}
            </Link>
          ))}
        </div>
        <HeaderUtilityActions manageHref={queryHref(MANAGE_LINK.href, { platform })} />
      </div>
    </nav>
  );
}
