import { randomUUID } from "node:crypto";
import type { ReactNode } from "react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export { bytes } from "./units";

/** Скрытые поля каждой формы управления: CSRF, ожидаемая версия строки и код операции. */
export function fields(csrf: string, version = 0) {
  return <>
    <input type="hidden" name="csrf_token" value={csrf} />
    <input type="hidden" name="expected_row_version" value={version} />
    <input type="hidden" name="correlation_id" value={randomUUID()} />
  </>;
}

export function plural(value: number, one: string, few: string, many: string) {
  const n = Math.abs(value) % 100;
  return n > 10 && n < 20 ? many : n % 10 === 1 ? one : n % 10 >= 2 && n % 10 <= 4 ? few : many;
}

/** «5 мин назад» относительно момента отрисовки страницы. */
export function ago(value: string | null | undefined, now: number) {
  if (!value) return "—";
  const seconds = Math.max(0, (now - Date.parse(value)) / 1000);
  if (seconds < 90) return "только что";
  if (seconds < 3600) return `${Math.round(seconds / 60)} мин назад`;
  if (seconds < 48 * 3600) return `${(seconds / 3600).toFixed(1).replace(".", ",")} ч назад`;
  return `${Math.round(seconds / 86400)} сут назад`;
}

/** Карточка раздела панели: заголовок, пояснение, действия справа. */
export function Section({ title, description, action, children, className, ...rest }: {
  title: string; description?: ReactNode; action?: ReactNode; children?: ReactNode; className?: string;
} & Record<`data-${string}`, string>) {
  return (
    <Card className={cn("mb-5 block min-w-0 p-5 text-sm", className)} {...rest}>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-heading text-lg font-semibold">{title}</h2>
          {description ? <p className="text-muted-foreground mt-2 text-sm leading-relaxed">{description}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </Card>
  );
}

export function Pill({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("bg-muted inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium", className)}>{children}</span>;
}
