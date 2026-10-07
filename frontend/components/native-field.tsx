"use client";

import { useEffect, useId, useRef, useState, useSyncExternalStore, type ChangeEvent, type ReactNode } from "react";
import * as m from "motion/react-m";

const subscribeNever = () => () => {};
const SLIDE = { type: "spring", stiffness: 420, damping: 36 } as const;

/**
 * A segmented control built from real radio inputs.
 *
 * The filter forms submit by GET and depend on the browser restoring their
 * controls on back and forward navigation. shadcn's Tabs and ToggleGroup keep
 * their state in Base UI, which form.reset() and assigning to checked cannot
 * drive, so this control keeps the radios and borrows the TabsList look.
 *
 * Без скриптов выбранный пункт подсвечивает CSS (peer-checked). После
 * гидратации подсветку рисует подложка animate-ui-стиля: она переезжает к
 * выбранному пункту пружиной. Состояние по-прежнему живёт в самих radio —
 * компонент лишь следит за ними (change, reset формы, возврат по истории).
 */
export function NativeSegments({ name, options, value, legend, labelled = true, stretch = false }: {
  name: string;
  legend: string;
  value: string;
  options: readonly { value: string; label: string; title?: string; icon?: ReactNode }[];
  /** В компактной панели подпись мешает: набор и так читается по значениям. */
  labelled?: boolean;
  stretch?: boolean;
}) {
  const id = useId();
  const group = useRef<HTMLDivElement>(null);
  const hydrated = useSyncExternalStore(subscribeNever, () => true, () => false);
  const [current, setCurrent] = useState(value);
  useEffect(() => {
    const node = group.current;
    if (!node) return;
    const sync = () => {
      const checked = node.querySelector<HTMLInputElement>("input:checked");
      if (checked) setCurrent(checked.value);
    };
    // Браузер восстанавливает отметки при возврате по истории, а reset формы
    // сбрасывает их без события change: в обоих случаях перечитываем radio.
    const form = node.closest("form");
    const onReset = () => window.setTimeout(sync);
    window.addEventListener("pageshow", sync);
    form?.addEventListener("reset", onReset);
    form?.addEventListener("segments-sync", sync);
    const frame = window.requestAnimationFrame(sync);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("pageshow", sync);
      form?.removeEventListener("reset", onReset);
      form?.removeEventListener("segments-sync", sync);
    };
  }, []);
  return (
    <fieldset className="m-0 grid gap-1.5 border-0 p-0">
      <legend className="sr-only">{legend}</legend>
      {labelled ? <span className="text-muted-foreground text-sm font-medium" aria-hidden="true">{legend}</span> : null}
      <div ref={group} data-testid={`${name}-segments`} data-animated={hydrated || undefined}
        onChange={(event: ChangeEvent<HTMLDivElement>) => {
          const target = event.target as unknown as HTMLInputElement;
          if (target.name === name && target.checked) setCurrent(target.value);
        }}
        className={`group/segments bg-muted text-muted-foreground flex h-8 max-w-full items-center overflow-x-auto rounded-lg p-[3px] ${stretch ? "w-full" : "w-fit"}`}>
        {options.map((option) => (
          <label key={option.value} className={`relative m-0 h-full cursor-pointer ${stretch ? "min-w-0 flex-1" : "shrink-0"}`} title={option.title ?? option.label}>
            <input type="radio" name={name} value={option.value} aria-label={option.icon ? option.label : undefined} defaultChecked={option.value === value} className="peer absolute inset-0 z-10 h-full w-full cursor-pointer opacity-0" />
            {hydrated && current === option.value ? (
              <m.span layoutId={`segment-${id}`} transition={SLIDE} aria-hidden="true"
                className="bg-background dark:border-input dark:bg-input/30 absolute inset-0 rounded-md border border-transparent shadow-sm" />
            ) : null}
            <span className={`text-foreground/60 hover:text-foreground dark:text-muted-foreground dark:hover:text-foreground peer-checked:bg-background peer-checked:text-foreground dark:peer-checked:border-input dark:peer-checked:bg-input/30 peer-focus-visible:border-ring peer-focus-visible:ring-ring/50 relative grid h-full place-items-center rounded-md border border-transparent text-sm font-medium whitespace-nowrap transition-colors peer-checked:shadow-sm peer-focus-visible:ring-[3px] group-data-[animated]/segments:peer-checked:border-transparent group-data-[animated]/segments:peer-checked:bg-transparent group-data-[animated]/segments:peer-checked:shadow-none dark:group-data-[animated]/segments:peer-checked:bg-transparent ${stretch ? "min-w-0 px-1.5" : "min-w-10 px-2.5"}`}>
              {option.icon ?? option.label}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
