"use client";

import { useDeferredValue, useMemo, useState } from "react";
import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from "@/components/ui/combobox";
import { prepareTargets, searchInstitutions } from "@/lib/institution-search";
import type { FindingInstitution } from "@/lib/types";

const label = (item: FindingInstitution) => item.shortName || item.canonicalName;

/** Поле поиска вуза. Отдельный модуль: Combobox тяжёлый и нужен только в
 *  режиме «Мой вуз», поэтому InstitutionPicker подгружает его отдельно. */
export function InstitutionCombobox({ institutions, value, onChoose }: {
  institutions: FindingInstitution[]; value: number | null; onChoose: (item: FindingInstitution) => void;
}) {
  const [selected, setSelected] = useState<FindingInstitution | null>(
    () => institutions.find((item) => item.legacyId === value) ?? null);
  // Поиск по обоим названиям с ранжированием (lib/institution-search). После
  // выбора поле показывает название вуза — список при этом остаётся полным.
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const prepared = useMemo(() => prepareTargets(institutions,
    (item) => ({ shortName: item.shortName, name: item.canonicalName })), [institutions]);
  const filtered = useMemo(() => searchInstitutions(prepared, deferred), [prepared, deferred]);
  return (
    <Combobox items={institutions} filteredItems={filtered} filter={null} value={selected} itemToStringLabel={label}
      isItemEqualToValue={(item, current) => item.legacyId === current.legacyId}
      onInputValueChange={(next, details) => setQuery(details.reason === "input-change" ? next : "")}
      onValueChange={(item) => { setSelected(item); if (item) onChoose(item); }}>
      <ComboboxInput placeholder="Выберите вуз" aria-label="Вуз" className="h-8 w-full text-sm md:text-sm" />
      <ComboboxContent>
        <ComboboxEmpty>Вуз не найден</ComboboxEmpty>
        <ComboboxList>
          {(item: FindingInstitution) => (
            <ComboboxItem key={item.legacyId} value={item} className="pr-7">
              <span className="min-w-0">
                <span className="block font-medium">{label(item)}</span>
                {item.shortName ? <span className="text-muted-foreground block truncate text-xs">{item.canonicalName}</span> : null}
              </span>
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
