"use client";

import { Megaphone } from "lucide-react";
import { MethodNote } from "@/components/method-note";
import { FINDINGS_PROMOTION_OPTIONS, type FindingsPromotion } from "@/lib/findings";

/** Посты с пометкой «похоже на продвижение» (ВК): все, только они или без
 *  них. Список принадлежит форме фильтров (атрибут form) и отправляет её сам. */
export function PromotionFilter({ form, value }: { form: string; value: FindingsPromotion }) {
  return <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
    <label className="text-muted-foreground inline-flex items-center gap-1.5">
      <Megaphone className="size-3.5 text-sky-600 dark:text-sky-400" aria-hidden="true" />
      <span>Продвижение ВК:</span>
      <select id="findings-promotion" data-testid="findings-promotion-filter" name="promotion" form={form}
        defaultValue={value}
        className="border-input bg-background text-foreground h-8 rounded-md border px-2 text-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        onChange={() => (document.getElementById(form) as HTMLFormElement | null)?.requestSubmit()}>
        {FINDINGS_PROMOTION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
    <MethodNote title="Похоже на продвижение">
      Пометка поста ВК: двое суток подряд и больше просмотров во много раз больше, чем у постов аккаунта того же
      возраста, ночью почти нет, а реакций на просмотр мало — так выглядят показы рекламы записи, которые ВК
      засчитывает как просмотры. Это контекст поста, а не уровень аномалии: признаки поста остаются как есть.
      Пометка не доказывает, что запись продвигали платно.
    </MethodNote>
  </div>;
}
