import contributors from "@/lib/contributors.generated.json";
import { plural } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Авторы проекта рядом со знаком GitHub. Аватары сложены стопкой и
 *  раздвигаются при наведении; подсказка с именем и числом коммитов — на CSS:
 *  всплывающие подсказки Base UI тянули в каждую страницу ~40 КиБ скрипта.
 *  Список обновляет pnpm generate:contributors, файлы лежат в самом сайте. */
export function Contributors({ className }: { className?: string }) {
  if (!contributors.length) return null;
  return (
    // Разметка AvatarGroup из shadcn: сам модуль ui/avatar тянет примитив Base UI
    // в каждую страницу, а стопке нужен только этот класс.
    <div data-slot="avatar-group" role="group" data-testid="contributors" aria-label="Авторы проекта"
      className={cn("group/avatar-group flex -space-x-2 items-center *:transition-[margin,translate,scale] *:duration-300 hover:space-x-1 focus-within:space-x-1 motion-reduce:*:transition-none", className)}>
      {contributors.map((person) => {
        const label = `${person.login} · ${person.contributions} ${plural(person.contributions, "коммит", "коммита", "коммитов")}`;
        return (
          <a key={person.login} href={person.url} target="_blank" rel="noopener noreferrer" aria-label={`${label} — профиль на GitHub`}
            className="group/person focus-visible:ring-ring/60 relative rounded-full outline-none hover:z-10 hover:-translate-y-0.5 hover:scale-110 focus-visible:z-10 focus-visible:ring-2">
            {/* Разметка аватара shadcn без примитива Base UI: файлы лежат в самом
                сайте и всегда загружаются, запасная буква не нужна. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={person.avatar} alt="" width={24} height={24} loading="lazy" decoding="async"
              className="ring-background bg-muted block size-6 rounded-full object-cover ring-2" />
            <span aria-hidden="true"
              className="bg-foreground text-background pointer-events-none absolute top-full left-1/2 z-50 mt-2 -translate-x-1/2 translate-y-1 rounded-md px-2.5 py-1 text-xs whitespace-nowrap opacity-0 shadow-md transition-[opacity,translate] duration-150 group-hover/person:translate-y-0 group-hover/person:opacity-100 group-focus-visible/person:translate-y-0 group-focus-visible/person:opacity-100">
              {label}
            </span>
          </a>
        );
      })}
    </div>
  );
}
