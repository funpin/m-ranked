import Link from "@/components/native-link";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { href: "/rating", label: "Прогноз М-Рейтинга" },
  { href: "/rating/own", label: "Наш рейтинг" },
] as const;

/** Два раздела «Рейтинга» — два адреса, как разделы «Находок». */
export function RatingTabs({ active }: { active: "/rating" | "/rating/own" }) {
  return <nav aria-label="Раздел рейтинга" data-testid="rating-tabs"
    className="bg-muted text-muted-foreground mb-5 inline-grid w-full grid-cols-2 rounded-lg p-[3px] sm:w-auto">
    {SECTIONS.map((section) => <Link key={section.href} href={section.href} prefetch={false}
      aria-current={section.href === active ? "page" : undefined}
      className={cn("rounded-md px-3 py-1 text-center text-sm font-medium whitespace-nowrap transition-colors",
        section.href === active ? "bg-background text-foreground shadow-sm" : "hover:text-foreground")}>
      {section.label}
    </Link>)}
  </nav>;
}
