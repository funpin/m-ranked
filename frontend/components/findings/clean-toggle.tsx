"use client";

import { EyeOff } from "lucide-react";
import { MethodNote } from "@/components/method-note";
import { formatInteger } from "@/lib/compare-dashboard";
import { cn } from "@/lib/utils";

/** «Скрыть аккаунты с устойчивыми находками» — как переключатель вузов на
 *  сравнении. Флажок принадлежит форме фильтров (атрибут form) и отправляет
 *  её сам: он стоит под панелью, а не внутри неё. */
export function CleanToggle({ form, clean, count }: { form: string; clean: boolean; count: number }) {
  return <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
    <label data-testid="findings-clean-toggle"
      className={cn("border-input hover:bg-muted inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border px-2.5 transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
        clean ? "bg-muted text-foreground" : "text-muted-foreground")}>
      <input type="checkbox" name="clean" value="1" form={form} defaultChecked={clean} className="sr-only"
        onChange={() => (document.getElementById(form) as HTMLFormElement | null)?.requestSubmit()} />
      <EyeOff className="size-3.5" aria-hidden="true" />
      Скрыть аккаунты с устойчивыми находками ({formatInteger(count)})
    </label>
    <MethodNote title="Устойчивые находки">
      Аккаунтные находки — закономерности многих постов аккаунта за 30 дней относительно аккаунтов площадки:
      повторяющиеся пакеты, волны просмотров по стене, слишком ровный отклик, ночные реакции и другие. «Устойчиво» —
      в обеих половинах окна; значок у поста — красный. Переключатель убирает посты таких аккаунтов из выдачи.
      Находка — статистическая необычность, а не доказательство накрутки.
    </MethodNote>
  </div>;
}
