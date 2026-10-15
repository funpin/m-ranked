import Link from "@/components/native-link";
import { FINDINGS_VIEW_OPTIONS, findingsPath, viewHrefQuery, type ParsedFindingsQuery } from "@/lib/findings";
import { queryHref } from "@/lib/params";
import { cn } from "@/lib/utils";

/** Два раздела «Находок». Обычные ссылки: раздел — свой адрес, отбор
 *  (площадка, период, вуз, поиск) переносится, сортировка у раздела своя. */
export function FindingsViewTabs({ query }: { query: ParsedFindingsQuery }) {
  return <nav aria-label="Раздел находок" data-testid="findings-view-tabs"
    className="bg-muted text-muted-foreground mb-3 inline-grid w-full grid-cols-2 rounded-lg p-[3px] sm:w-auto">
    {FINDINGS_VIEW_OPTIONS.map((option) => {
      const active = option.value === query.view;
      return <Link key={option.value} href={queryHref(findingsPath(option.value), viewHrefQuery(query))} prefetch={false}
        aria-current={active ? "page" : undefined} title={option.title}
        className={cn("rounded-md px-3 py-1 text-center text-sm font-medium whitespace-nowrap transition-colors",
          active ? "bg-background text-foreground shadow-sm" : "hover:text-foreground")}>
        {option.label}
      </Link>;
    })}
  </nav>;
}
