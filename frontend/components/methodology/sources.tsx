import type { ReactNode } from "react";
import { BookOpen } from "lucide-react";

/** Основания метода: работы и материалы, на которые он опирается. */
export function Sources({ children }: { children: ReactNode }) {
  return (
    <aside aria-label="Основания метода"
      className="bg-muted/40 ring-foreground/5 my-6 grid gap-1 rounded-xl px-4 py-3 text-sm ring-1 [&_li]:text-sm [&_ul]:my-1 [&_ul]:space-y-1">
      <p className="text-muted-foreground inline-flex items-center gap-2 text-xs font-medium tracking-[0.12em] uppercase">
        <BookOpen className="size-3.5" aria-hidden="true" />Основания
      </p>
      {children}
    </aside>
  );
}
