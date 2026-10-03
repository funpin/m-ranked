"use client";

import { beginNavigation } from "@/lib/navigation-pending";
import { useRouter } from "next/navigation";
import { useRef, useTransition, type ComponentProps } from "react";
import { useStuck } from "@/components/use-stuck";

const replacing = new WeakSet<HTMLFormElement>();

/** Отправка, которая заменяет текущую запись истории, а не добавляет новую:
 *  для автоматического шага (восстановленный вуз), иначе «Назад» вернул бы на
 *  пустой выбор, откуда страница снова ушла бы вперёд. */
export function requestReplaceSubmit(form: HTMLFormElement) {
  replacing.add(form);
  form.requestSubmit();
}

/** GET-форма фильтров: работает и без скриптов, со скриптами — без перезагрузки.
 *
 *  Повторяемые поля (`types`) идут через append. Сразу отправляются только
 *  выпадающие списки и переключатели, принадлежащие самой форме: флажки панели
 *  «Фильтры» живут в портале, сами обновляют скрытые поля и отправляют форму,
 *  а React доносит их событие сюда — без этой проверки отправка ушла бы дважды. */
export function FindingsFilterForm(props: ComponentProps<"form">) {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const [pending, startTransition] = useTransition();
  useStuck(formRef);

  function navigate(form: HTMLFormElement) {
    const query = new URLSearchParams();
    const data = new FormData(form);
    // Вуз осмыслен только в режиме «Мой вуз»: после возврата к «Все вузы»
    // скрытое поле ещё в форме, но в адрес попадать не должно.
    const institutionMode = data.get("mode") === "institution";
    data.forEach((value, key) => {
      if (key === "institution" && !institutionMode) return;
      if (typeof value === "string" && value !== "") query.append(key, value);
    });
    const replace = replacing.delete(form);
    beginNavigation();
    const href = `/statistics?${query}`;
    startTransition(() => replace ? router.replace(href, { scroll: false }) : router.push(href, { scroll: false }));
  }

  return (
    <form {...props} ref={formRef} aria-busy={pending}
      onChange={(event) => {
        const field = event.target;
        if (!(field instanceof HTMLSelectElement || field instanceof HTMLInputElement)) return;
        if (field.form !== event.currentTarget || !field.name) return;
        if (field instanceof HTMLSelectElement || field.type === "radio" || field.type === "checkbox") {
          event.currentTarget.requestSubmit();
        }
      }}
      onSubmit={(event) => { event.preventDefault(); navigate(event.currentTarget); }}>
      {props.children}
      <span className="sr-only" role="status" hidden={!pending}>Обновляю…</span>
    </form>
  );
}
