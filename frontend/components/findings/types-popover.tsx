"use client";

import { SlidersHorizontal } from "lucide-react";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Button } from "@/components/ui/button";
import { FINDINGS_TYPE_OPTIONS, type FindingsGroup, type FindingsType } from "@/lib/findings";

type Panel = typeof import("@/components/findings/types-popover-panel").TypesPopoverPanel;
let panelModule: Promise<Panel> | null = null;
// Как у заметки о методике: панель приезжает по первому наведению или нажатию.
// Обычная кнопка остаётся на месте, пока модуль не доехал, — без пустого кадра.
const loadPanel = () => (panelModule ??= import("@/components/findings/types-popover-panel")
  .then((module) => module.TypesPopoverPanel)
  .catch((error: unknown) => { panelModule = null; throw error; }));

/** Редкие фильтры: тип публикации и группировка. Счётчик — число активных.
 *
 *  Popover рендерит содержимое в портал и, закрытый, вынимает его из DOM —
 *  поля внутри него форма бы теряла при любой другой отправке. Поэтому
 *  значения живут в скрытых полях самой формы (они же работают без скриптов),
 *  а флажки панели безымянные: меняют состояние и сами отправляют форму. */
export function TypesPopover({ value, group, groupAvailable }: {
  value: FindingsType[]; group: FindingsGroup; groupAvailable: boolean;
}) {
  const fields = useRef<HTMLSpanElement>(null);
  const [types, setTypes] = useState(value);
  const [grouping, setGrouping] = useState<FindingsGroup>(groupAvailable ? group : "none");
  // Пока не пришёл указатель или нажатие, вместо Popover — обычная кнопка.
  const [panel, setPanel] = useState<{ Component: Panel } | null>(null);
  const active = types.length + (grouping === "institution" ? 1 : 0);

  const triggerContent = <><SlidersHorizontal aria-hidden="true" />Фильтры{active ? <span className="tabular-nums">· {active}</span> : null}</>;

  // Наведение только подгружает модуль: подменять кнопку под указателем
  // посреди нажатия нельзя — щелчок уйдёт в никуда. Подмена — по нажатию,
  // и панель сразу открыта.
  function open() {
    loadPanel().then((Component) => setPanel((current) => current ?? { Component }), () => undefined);
  }

  function apply(update: () => void) {
    flushSync(update);
    fields.current?.closest("form")?.requestSubmit();
  }

  return <>
    <span ref={fields} hidden>
      {types.map((type) => <input key={type} type="hidden" name="types" value={type} />)}
      {grouping === "institution" ? <input type="hidden" name="group" value="institution" /> : null}
    </span>
    {!panel ? (
      <Button type="button" variant="outline" size="sm" className="h-8" aria-haspopup="dialog"
        onPointerEnter={() => void loadPanel().catch(() => undefined)} onClick={open}>
        {triggerContent}
      </Button>
    ) : (
      <panel.Component label={triggerContent} defaultOpen>
        <fieldset className="space-y-2">
          <legend className="mb-2 text-sm font-medium">Тип публикации</legend>
          {FINDINGS_TYPE_OPTIONS.map(([type, label]) => (
            <label key={type} className="flex items-center gap-2">
              <input type="checkbox" checked={types.includes(type)} className="accent-primary size-4"
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  apply(() => setTypes((current) => FINDINGS_TYPE_OPTIONS.map(([option]) => option)
                    .filter((option) => option === type ? checked : current.includes(option))));
                }} />
              {label}
            </label>
          ))}
        </fieldset>
        {groupAvailable ? (
          <fieldset className="space-y-2">
            <legend className="mb-2 text-sm font-medium">Показать</legend>
            {(["none", "institution"] as const).map((option) => (
              <label key={option} className="flex items-center gap-2">
                <input type="radio" name="findings-grouping" checked={grouping === option} className="accent-primary size-4"
                  onChange={() => apply(() => setGrouping(option))} />
                {option === "none" ? "Списком" : "По вузам"}
              </label>
            ))}
          </fieldset>
        ) : null}
      </panel.Component>
    )}
  </>;
}
