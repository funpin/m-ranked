"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef } from "react";
import { requestReplaceSubmit } from "@/components/findings/filter-form";
import { recallInstitution, rememberInstitution } from "@/lib/findings";
import type { FindingInstitution } from "@/lib/types";

// Combobox со своим позиционером и списком весит десятки КиБ, а нужен только
// в режиме «Мой вуз»: в первую загрузку «Все вузы» он не попадает. Заглушка
// той же высоты и ширины, чтобы панель не прыгала.
const InstitutionCombobox = dynamic(
  () => import("@/components/findings/institution-combobox").then((module) => module.InstitutionCombobox),
  { loading: () => <div aria-hidden="true" className="border-input h-8 w-full rounded-md border sm:w-64" /> },
);

function browserStorage(): Storage | null {
  try { return window.localStorage; } catch { return null; }
}

/** Вуз режима «Мой вуз». Значение уходит в форму скрытым полем; выбор
 *  запоминается в localStorage только как удобство следующего визита. */
export function InstitutionPicker({ institutions, value }: { institutions: FindingInstitution[]; value: number | null }) {
  const hidden = useRef<HTMLInputElement>(null);
  const restored = useRef(false);

  function submit(item: FindingInstitution, restoring = false) {
    const form = hidden.current?.form;
    if (!hidden.current || !form) return;
    rememberInstitution(browserStorage(), item.legacyId);
    hidden.current.value = String(item.legacyId);
    if (restoring) requestReplaceSubmit(form);
    else form.requestSubmit();
  }

  useEffect(() => {
    // Только при первом показе пустого режима и только один раз: после
    // отправки страница приходит уже с вузом, и value перестаёт быть null.
    if (value !== null || restored.current) return;
    restored.current = true;
    const remembered = recallInstitution(browserStorage());
    const item = institutions.find((entry) => entry.legacyId === remembered);
    if (item) submit(item, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <>
    <input ref={hidden} type="hidden" name="institution" defaultValue={value ?? ""} />
    <InstitutionCombobox institutions={institutions} value={value} onChoose={(item) => submit(item)} />
  </>;
}
