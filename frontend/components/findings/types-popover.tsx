"use client";

import { SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { FINDINGS_TYPE_OPTIONS, type FindingsGroup, type FindingsType } from "@/lib/findings";

type Panel = typeof import("@/components/findings/types-popover-panel").TypesPopoverPanel;
let panelModule: Promise<Panel> | null = null;
let loadedPanel: Panel | null = null;
// Как у заметки о методике: панель приезжает по первому наведению или нажатию.
// Обычная кнопка остаётся на месте, пока модуль не доехал, — без пустого кадра.
const loadPanel = () => (panelModule ??= import("@/components/findings/types-popover-panel")
  .then((module) => (loadedPanel = module.TypesPopoverPanel))
  .catch((error: unknown) => { panelModule = null; throw error; }));

// Отправка по закрытию панели пересоздаёт форму вместе с кнопкой «Фильтры»;
// новый экземпляр возвращает фокус на свою кнопку.
let refocusTrigger = false;

const sameTypes = (left: readonly FindingsType[], right: readonly FindingsType[]) =>
  left.length === right.length && left.every((type) => right.includes(type));

/** Редкие фильтры: тип публикации и группировка. Счётчик — число активных.
 *
 *  Popover рендерит содержимое в портал и, закрытый, вынимает его из DOM —
 *  поля внутри него форма бы теряла при любой другой отправке. Поэтому
 *  значения живут в скрытых полях самой формы (они же работают без скриптов),
 *  а флажки панели безымянные. Форма отправляется при закрытии панели и только
 *  если что-то поменялось: иначе каждый флажок пересоздавал бы форму, панель
 *  закрывалась бы, а фокус терялся. */
export function TypesPopover({ value, group, groupAvailable }: {
  value: FindingsType[]; group: FindingsGroup; groupAvailable: boolean;
}) {
  const initialGroup: FindingsGroup = groupAvailable ? group : "none";
  const wrapper = useRef<HTMLSpanElement>(null);
  const [types, setTypes] = useState(value);
  const [grouping, setGrouping] = useState<FindingsGroup>(initialGroup);
  // Пока модуль панели не загружен, вместо Popover — обычная кнопка.
  const [panel, setPanel] = useState<{ Component: Panel; open: boolean } | null>(
    () => loadedPanel ? { Component: loadedPanel, open: false } : null);
  const active = types.length + (grouping === "institution" ? 1 : 0);

  useEffect(() => {
    if (!refocusTrigger) return;
    refocusTrigger = false;
    wrapper.current?.querySelector("button")?.focus();
  }, []);

  const triggerContent = <><SlidersHorizontal aria-hidden="true" />Фильтры{active ? <span className="tabular-nums">· {active}</span> : null}</>;

  // Наведение только подгружает модуль: подменять кнопку под указателем
  // посреди нажатия нельзя — щелчок уйдёт в никуда. Подмена — по нажатию,
  // и панель сразу открыта.
  function open() {
    loadPanel().then((Component) => setPanel((current) => current ?? { Component, open: true }), () => undefined);
  }

  function openChange(isOpen: boolean) {
    if (isOpen || (sameTypes(types, value) && grouping === initialGroup)) return;
    refocusTrigger = true;
    wrapper.current?.closest("form")?.requestSubmit();
  }

  return <span ref={wrapper} className="contents">
    <span hidden>
      {types.map((type) => <input key={type} type="hidden" name="types" value={type} />)}
      {grouping === "institution" ? <input type="hidden" name="group" value="institution" /> : null}
    </span>
    {!panel ? (
      <Button type="button" variant="outline" size="sm" className="h-8" aria-haspopup="dialog" aria-expanded="false"
        onPointerEnter={() => void loadPanel().catch(() => undefined)} onClick={open}>
        {triggerContent}
      </Button>
    ) : (
      <panel.Component label={triggerContent} defaultOpen={panel.open} onOpenChange={openChange}>
        <fieldset className="space-y-2">
          <legend className="mb-2 text-sm font-medium">Тип публикации</legend>
          {FINDINGS_TYPE_OPTIONS.map(([type, label]) => (
            <label key={type} className="flex items-center gap-2">
              <input type="checkbox" checked={types.includes(type)} className="accent-primary size-4"
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  setTypes((current) => FINDINGS_TYPE_OPTIONS.map(([option]) => option)
                    .filter((option) => option === type ? checked : current.includes(option)));
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
                  onChange={() => setGrouping(option)} />
                {option === "none" ? "Списком" : "По вузам"}
              </label>
            ))}
          </fieldset>
        ) : null}
      </panel.Component>
    )}
  </span>;
}
