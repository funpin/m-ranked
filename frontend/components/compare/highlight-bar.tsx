"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { Search, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import type { HighlightMap, InstitutionOption } from "@/lib/compare-dashboard";
import { cn } from "@/lib/utils";

const importCombobox = () => import("./highlight-combobox");

/** Заглушка того же вида, что поле поиска: видна сразу, без кода Combobox. */
function SearchShell({ value, onValue, onActivate }: {
  value?: string; onValue?: (value: string) => void; onActivate?: () => void;
}) {
  return (
    <InputGroup className="h-8">
      <InputGroupAddon><Search className="size-4" aria-hidden="true" /></InputGroupAddon>
      <InputGroupInput value={value ?? ""} placeholder="Выделить вуз на графиках…" aria-label="Найти вуз для выделения"
        className="text-sm md:text-sm" data-testid="highlight-search"
        onChange={(event) => { onValue?.(event.target.value); onActivate?.(); }}
        onFocus={onActivate} onPointerEnter={() => void importCombobox()} onTouchStart={() => void importCombobox()} />
    </InputGroup>
  );
}

const HighlightCombobox = dynamic(importCombobox, { ssr: false, loading: () => <SearchShell /> });

/** Выделенные вузы: поиск и цветные метки. Все вузы остаются на графиках —
 *  выделение только подсвечивает. Метки и их имена не зависят от вкладки. */
export function HighlightBar({ options, labels, highlights, onToggle, onClear, focusRequest }: {
  options: readonly InstitutionOption[]; labels: ReadonlyMap<string, { name: string; fullName: string }>;
  highlights: HighlightMap; onToggle: (id: string) => void; onClear: () => void; focusRequest: number;
}) {
  const [draft, setDraft] = useState("");
  const [active, setActive] = useState(false);
  const live = active || focusRequest > 0;
  const notes = new Map(options.map((option) => [option.id, option.note]));
  return (
    <div className="col-span-2 flex min-w-0 flex-wrap items-center gap-2 md:col-span-1">
      <div className="w-full">
        {live ? <HighlightCombobox options={options} highlights={highlights} onToggle={onToggle}
          initialQuery={draft} focusRequest={focusRequest} />
          : <SearchShell value={draft} onValue={setDraft} onActivate={() => setActive(true)} />}
      </div>
      {[...highlights].map(([id, color]) => {
        const label = labels.get(id);
        const note = notes.get(id);
        return (
          <Badge key={id} variant="outline" data-testid="highlight-chip" data-muted={note ? "true" : undefined}
            className={cn("max-w-full gap-1.5 rounded-full py-1 pr-1 pl-2", note && "text-muted-foreground border-dashed")}
            title={note ? `${label?.fullName ?? ""}: ${note}` : label?.fullName}>
            <span className="size-2.5 shrink-0 rounded-full" style={{ background: color }} aria-hidden="true" />
            <span className="min-w-0 truncate">{label?.name ?? id}</span>
            {note ? <span className="sr-only">: {note}</span> : null}
            <Button variant="ghost" size="icon-xs" className="rounded-full" onClick={() => onToggle(id)}
              aria-label={`Снять выделение: ${label?.name ?? id}`}><X aria-hidden="true" /></Button>
          </Badge>
        );
      })}
      {highlights.size ? <Button variant="link" size="sm" className="text-muted-foreground hover:text-foreground px-1" onClick={onClear}>Сбросить</Button> : null}
    </div>
  );
}
