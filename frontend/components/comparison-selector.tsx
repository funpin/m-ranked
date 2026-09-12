"use client";

import { useState, type ReactNode } from "react";
import { Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface ComparisonCandidate { id: number; label: string; description: string }

export function ComparisonSelector({ candidates, selected, type, children, query = "", platformLabel = "Telegram" }: {
  candidates: ComparisonCandidate[];
  selected: number[];
  type: "channels" | "institutions";
  children: ReactNode;
  query?: string;
  platformLabel?: string;
}) {
  const [ids, setIds] = useState(() => new Set(selected));
  const [search, setSearch] = useState(query);
  const normalized = search.trim().toLocaleLowerCase("ru");

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="font-heading text-lg leading-none font-semibold">Настройка сравнения</h2>
          <p className="text-muted-foreground mt-2 text-sm">
            {type === "channels"
              ? "Выберите каналы и глубину истории публикаций."
              : `Выберите вузы и глубину истории публикаций ${platformLabel}.`}
          </p>
        </div>
        <output className="shrink-0" aria-live="polite">
          <Badge variant="secondary" className="rounded-full font-semibold tabular">
            Выбрано: {ids.size} из {candidates.length}
          </Badge>
        </output>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[230px] flex-1">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" aria-hidden="true" />
          <Input
            type="search"
            className="pl-9"
            aria-label={type === "channels" ? "Поиск канала" : "Поиск вуза"}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={type === "channels" ? "Найти вуз или @канал" : `Найти вуз или аккаунт ${platformLabel}`}
            autoComplete="off"
          />
        </div>
        <Button variant="outline" type="button" onClick={() => setIds(new Set(candidates.map((item) => item.id)))}>
          Выбрать все
        </Button>
        <Button variant="outline" type="button" onClick={() => setIds(new Set())}>
          Снять выбор
        </Button>
      </div>

      <p className="text-muted-foreground mt-3 text-sm">
        {type === "channels"
          ? "Для читаемого графика обычно достаточно выбрать 2–5 каналов. Линии также можно скрывать прямо в легенде."
          : "Для читаемого графика обычно достаточно 2–5 вузов. Несколько аккаунтов одной площадки у вуза объединяются."}
      </p>

      <div className="my-4 grid max-h-[268px] grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-2 overflow-auto p-0.5">
        {candidates.map((item) => {
          const checked = ids.has(item.id);
          return (
            <label
              key={item.id}
              hidden={!`${item.label} ${item.description}`.toLocaleLowerCase("ru").includes(normalized)}
              className={cn(
                "flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2.5 transition-colors",
                "hover:bg-accent has-[:focus-visible]:ring-ring/50 has-[:focus-visible]:ring-[3px]",
                checked && "border-primary/40 bg-accent",
              )}
            >
              {/* Native control: this selector submits through a plain GET form
                  and its state must survive history restoration. */}
              <input
                type="checkbox"
                name={type}
                value={item.id}
                checked={checked}
                className="accent-primary mt-0.5 size-4 shrink-0"
                onChange={(event) => setIds((previous) => {
                  const next = new Set(previous);
                  if (event.target.checked) next.add(item.id); else next.delete(item.id);
                  return next;
                })}
              />
              <span className="min-w-0">
                <span className="block leading-snug font-semibold">{item.label}</span>
                <span className="text-muted-foreground mt-0.5 block text-xs">{item.description}</span>
              </span>
            </label>
          );
        })}
      </div>

      {children}
    </>
  );
}
