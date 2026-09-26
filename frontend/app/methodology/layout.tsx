import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { DocsSidebar } from "@/components/methodology/docs-sidebar";

/** Раздел методологии: меню слева, на узком экране — раскрывающийся список. */
export default function MethodologyLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid gap-8 lg:grid-cols-[232px_minmax(0,1fr)] xl:gap-14" data-testid="methodology">
      <aside className="max-lg:hidden">
        <div className="sticky top-20 max-h-[calc(100svh-6rem)] overflow-y-auto pr-2 pb-8">
          <DocsSidebar />
        </div>
      </aside>
      <div className="min-w-0">
        <details className="group bg-card ring-foreground/10 mb-8 rounded-xl ring-1 lg:hidden">
          <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
            Разделы методологии
            <ChevronDown className="text-muted-foreground size-4 transition-transform group-open:rotate-180" aria-hidden="true" />
          </summary>
          <div className="border-t p-2"><DocsSidebar /></div>
        </details>
        {children}
      </div>
    </div>
  );
}
