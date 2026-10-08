"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from "@/components/ui/combobox";
import { InputGroupAddon } from "@/components/ui/input-group";
import { MAX_HIGHLIGHTS, type HighlightMap, type InstitutionOption } from "@/lib/compare-dashboard";
import { prepareTargets, searchInstitutions } from "@/lib/institution-search";

/** Поиск вуза для выделения. Отдельный модуль: Combobox тяжёлый, поэтому
 *  HighlightBar подгружает его по первому касанию поля. */
export default function HighlightCombobox({ options, highlights, onToggle, initialQuery, focusRequest }: {
  options: readonly InstitutionOption[]; highlights: HighlightMap; onToggle: (id: string) => void;
  initialQuery: string; focusRequest: number;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState(initialQuery);
  const deferred = useDeferredValue(query);
  const prepared = useMemo(() => prepareTargets(options,
    (option) => ({ shortName: option.name, name: option.fullName, weight: option.weight })), [options]);
  const filtered = useMemo(() => searchInstitutions(prepared, deferred), [prepared, deferred]);
  const selected = useMemo(() => options.filter((option) => highlights.has(option.id)), [options, highlights]);
  const full = highlights.size >= MAX_HIGHLIGHTS;

  // Поле заменило заглушку под пальцем или курсором: фокус остаётся в поиске.
  useEffect(() => { input.current?.focus(); }, [focusRequest]);

  return (
    <Combobox multiple items={options as InstitutionOption[]} filteredItems={filtered} filter={null} autoHighlight
      value={selected} isItemEqualToValue={(item, value) => item.id === value.id} itemToStringLabel={(item) => item.name}
      inputValue={query} onInputValueChange={(next) => setQuery(next)} defaultOpen={Boolean(initialQuery)}
      onValueChange={(next) => {
        const ids = new Set(next.map((item) => item.id));
        for (const option of selected) if (!ids.has(option.id)) onToggle(option.id);
        for (const id of ids) if (!highlights.has(id)) onToggle(id);
        setQuery("");
      }}>
      <ComboboxInput ref={input} showTrigger={false} data-testid="highlight-search" aria-label="Найти вуз для выделения"
        placeholder={full ? `Выделено ${MAX_HIGHLIGHTS} из ${MAX_HIGHLIGHTS} — снимите вуз, чтобы добавить` : "Выделить вуз на графиках…"}
        className="h-8 w-full text-sm md:text-sm">
        <InputGroupAddon><Search className="size-4" aria-hidden="true" /></InputGroupAddon>
      </ComboboxInput>
      <ComboboxContent>
        <ComboboxEmpty>Ничего не найдено</ComboboxEmpty>
        <ComboboxList>
          {(option: InstitutionOption) => {
            const color = highlights.get(option.id);
            return (
              <ComboboxItem key={option.id} value={option} disabled={full && !color} className="items-start pr-7">
                <span className="mt-1 size-2.5 shrink-0 rounded-full border" style={{ background: color ?? "transparent" }} aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="truncate font-medium">{option.name}</span>
                    {option.note ? <span className="text-muted-foreground shrink-0 text-[11px]">{option.note}</span> : null}
                  </span>
                  {option.fullName !== option.name
                    ? <span className="text-muted-foreground block truncate">{option.fullName}</span> : null}
                </span>
              </ComboboxItem>
            );
          }}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
