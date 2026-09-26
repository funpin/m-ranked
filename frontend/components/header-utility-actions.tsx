import type { ReactNode } from "react";
import { Settings } from "lucide-react";
import Link from "@/components/native-link";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ThemeToggle } from "@/components/theme-toggle";
import { HEADER_BUTTON } from "@/components/header-button";
import { Contributors } from "@/components/contributors";
import { GithubMark } from "@/components/github-mark";
import { REPOSITORY_URL } from "@/lib/repository";

/**
 * Правая часть шапки общая для живого варианта и серверной заготовки.
 * Иначе при медленной гидратации пользователь видит прежнюю урезанную шапку.
 */
export function HeaderUtilityActions({ menuToggle, manageHref, manageActive = false }: {
  menuToggle?: ReactNode; manageHref: string; manageActive?: boolean;
}) {
  return (
    <div data-testid="header-utility-actions" className="ml-auto flex shrink-0 items-center gap-1">
      {/* Авторы и знак GitHub — одна группа, без разделителя между ними. */}
      <Contributors className="mr-1.5 max-[780px]:hidden" />
      <a href={REPOSITORY_URL} target="_blank" rel="noopener noreferrer" aria-label="Исходный код на GitHub"
        title="Исходный код на GitHub" className={cn(buttonVariants({ variant: "ghost", size: "icon" }), HEADER_BUTTON)}>
        <GithubMark className="size-[1.15rem]" />
      </a>
      <Separator orientation="vertical" className="mx-2 h-5 data-vertical:self-center max-[780px]:hidden" />
      {/* Управление — служебный раздел: значок между GitHub и темой, а не
          пункт основного меню. В мобильном меню он остаётся текстом. */}
      {/* Обычная ссылка в облике кнопки: Base UI Button навязал бы ей роль button. */}
      <Link href={manageHref} prefetch={false} data-testid="manage-link" aria-label="Управление" title="Управление"
        aria-current={manageActive ? "page" : undefined}
        className={cn(buttonVariants({ variant: "ghost", size: "icon" }), HEADER_BUTTON, "max-[780px]:hidden",
          manageActive && "bg-foreground/[0.07] dark:bg-foreground/10")}>
        <Settings className="size-[1.15rem]" aria-hidden="true" />
      </Link>
      <Separator orientation="vertical" className="mx-2 h-5 data-vertical:self-center" />
      <ThemeToggle />
      {menuToggle}
    </div>
  );
}
