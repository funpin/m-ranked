import Link from "@/components/native-link";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { href: "/rating/own", label: "М-Рейтинг без накрутки" },
  { href: "/rating/own/formula", label: "Наша формула" },
] as const;

export type OwnSection = (typeof SECTIONS)[number]["href"];

/** Подразделы «Нашего рейтинга»: пересчёт М-Рейтинга без накрутки и собственная формула. */
export function OwnTabs({ active }: { active: OwnSection }) {
  return <nav aria-label="Подраздел нашего рейтинга" data-testid="own-tabs" className="mb-5 flex flex-wrap gap-x-5 gap-y-1 border-b">
    {SECTIONS.map((section) => <Link key={section.href} href={section.href} prefetch={false}
      aria-current={section.href === active ? "page" : undefined}
      className={cn("-mb-px border-b-2 py-2 text-sm font-medium whitespace-nowrap transition-colors",
        section.href === active ? "border-foreground text-foreground" : "text-muted-foreground hover:text-foreground border-transparent")}>
      {section.label}
    </Link>)}
  </nav>;
}
