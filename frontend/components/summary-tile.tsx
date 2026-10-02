import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { MethodNote } from "@/components/method-note";

export function SummaryTile({ label, value, icon, note, trailing, footer, compactValue = false, valueSlot = "account-summary-value" }: {
  label: string; value: ReactNode; icon?: ReactNode; note?: string;
  trailing?: ReactNode; footer?: ReactNode; compactValue?: boolean; valueSlot?: string;
}) {
  return <Card size="sm" className="h-full bg-background/30 ring-border/70 data-[size=sm]:[--card-spacing:--spacing(2.5)]">
    <CardContent>
      <dl className="grid min-w-0 gap-1">
        <dt className="flex min-w-0 items-start gap-1.5 text-xs leading-4 text-muted-foreground">
          {icon ? <span aria-hidden="true" className="mt-px hidden shrink-0 sm:inline-flex [&>svg]:size-3.5">{icon}</span> : null}
          <span className="min-w-0 flex-1">{label}</span>
          {note ? <MethodNote title={label}>{note}</MethodNote> : null}
        </dt>
        <dd className="flex min-w-0 flex-wrap items-center justify-between gap-x-2 gap-y-1">
          <span data-slot={valueSlot} className={`font-heading font-semibold tracking-tight tabular-nums ${compactValue ? "text-lg leading-8 sm:text-xl" : "text-2xl leading-8"}`}>{value}</span>
          {trailing ? <span className="shrink-0">{trailing}</span> : null}
        </dd>
        {footer ? <dd className="text-xs leading-4 text-muted-foreground">{footer}</dd> : null}
      </dl>
    </CardContent>
  </Card>;
}
