"use client";

import { useState } from "react";
import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from "@/components/ui/combobox";
import type { FindingInstitution } from "@/lib/types";

const label = (item: FindingInstitution) => item.shortName || item.canonicalName;

/** Поиск по обоим названиям: короткое видно в поле, полное — строкой ниже. */
function matches(item: FindingInstitution, query: string) {
  const needle = query.trim().toLocaleLowerCase("ru-RU");
  if (!needle) return true;
  return [item.shortName, item.canonicalName].some((name) => name?.toLocaleLowerCase("ru-RU").includes(needle));
}

/** Поле поиска вуза. Отдельный модуль: Combobox тяжёлый и нужен только в
 *  режиме «Мой вуз», поэтому InstitutionPicker подгружает его отдельно. */
export function InstitutionCombobox({ institutions, value, onChoose }: {
  institutions: FindingInstitution[]; value: number | null; onChoose: (item: FindingInstitution) => void;
}) {
  const [selected, setSelected] = useState<FindingInstitution | null>(
    () => institutions.find((item) => item.legacyId === value) ?? null);
  return (
    <Combobox items={institutions} value={selected} itemToStringLabel={label} filter={matches}
      isItemEqualToValue={(item, current) => item.legacyId === current.legacyId}
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
