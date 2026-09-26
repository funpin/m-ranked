"use client";

import { usePathname } from "next/navigation";
import { BookOpen, Braces } from "lucide-react";
import Link from "@/components/native-link";
import { ARTICLES } from "@/lib/methodology";
import { cn } from "@/lib/utils";

const itemClass = (active: boolean) => cn(
  "block rounded-lg px-3 py-1.5 text-sm transition-colors",
  active ? "bg-muted text-foreground font-medium" : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
);

/** Меню раздела: обзор, статьи по порядку и справочник API. */
export function DocsSidebar() {
  const pathname = usePathname();
  return (
    <nav aria-label="Разделы методологии" className="grid gap-6">
      <div className="grid gap-1">
        <p className="text-muted-foreground mb-1 inline-flex items-center gap-2 px-3 text-xs font-medium tracking-[0.12em] uppercase">
          <BookOpen className="size-3.5" aria-hidden="true" />Методология
        </p>
        <Link href="/methodology" prefetch={false} aria-current={pathname === "/methodology" ? "page" : undefined}
          className={itemClass(pathname === "/methodology")}>Обзор</Link>
        <ol className="grid gap-0.5">
          {ARTICLES.map((article, index) => {
            const href = `/methodology/${article.slug}`;
            return (
              <li key={article.slug}>
                <Link href={href} prefetch={false} aria-current={pathname === href ? "page" : undefined} className={itemClass(pathname === href)}>
                  <span className="text-muted-foreground/70 mr-2 font-mono text-xs tabular-nums">{index + 1}</span>{article.title}
                </Link>
              </li>
            );
          })}
        </ol>
      </div>
      <div className="grid gap-1">
        <p className="text-muted-foreground mb-1 inline-flex items-center gap-2 px-3 text-xs font-medium tracking-[0.12em] uppercase">
          <Braces className="size-3.5" aria-hidden="true" />Данные
        </p>
        <Link href="/methodology/api" prefetch={false} aria-current={pathname === "/methodology/api" ? "page" : undefined}
          className={itemClass(pathname === "/methodology/api")}>Открытый API</Link>
      </div>
    </nav>
  );
}
