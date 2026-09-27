import type { ComponentProps } from "react";
import { ChevronLeft, ChevronRight, MoreHorizontal } from "lucide-react";
import Link from "@/components/native-link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Shadcn Base UI composition, using the project's non-prefetching Next link. */
export function Pagination({ className, ...props }: ComponentProps<"nav">) {
  return <nav aria-label="Страницы обзора" data-slot="pagination" className={cn("flex w-full justify-center", className)} {...props} />;
}
export function PaginationContent({ className, ...props }: ComponentProps<"ul">) {
  return <ul data-slot="pagination-content" className={cn("flex items-center gap-1", className)} {...props} />;
}
export function PaginationItem(props: ComponentProps<"li">) {
  return <li data-slot="pagination-item" {...props} />;
}
export function PaginationLink({ isActive = false, className, ...props }: ComponentProps<typeof Link> & { isActive?: boolean }) {
  return <Link data-slot="pagination-link" aria-current={isActive ? "page" : undefined}
    className={cn(buttonVariants({ variant: isActive ? "outline" : "ghost", size: "icon-lg" }),
      "text-foreground no-underline", className)} {...props} />;
}
export function PaginationPrevious({ className, text = "Назад", ...props }: ComponentProps<typeof Link> & { text?: string }) {
  return <Link data-slot="pagination-previous" aria-label="Предыдущая страница"
    className={cn(buttonVariants({ variant: "ghost", size: "lg" }), "text-foreground no-underline", className)} {...props}>
    <ChevronLeft className="size-4" aria-hidden="true" /><span className="hidden sm:inline">{text}</span>
  </Link>;
}
export function PaginationNext({ className, text = "Далее", ...props }: ComponentProps<typeof Link> & { text?: string }) {
  return <Link data-slot="pagination-next" aria-label="Следующая страница"
    className={cn(buttonVariants({ variant: "ghost", size: "lg" }), "text-foreground no-underline", className)} {...props}>
    <span className="hidden sm:inline">{text}</span><ChevronRight className="size-4" aria-hidden="true" />
  </Link>;
}
export function PaginationEllipsis() {
  return <span data-slot="pagination-ellipsis" aria-hidden="true" className="flex size-8 items-center justify-center">
    <MoreHorizontal className="size-4" />
  </span>;
}
