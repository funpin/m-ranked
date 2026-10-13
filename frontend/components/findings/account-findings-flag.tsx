import { Flag } from "lucide-react";
import { FINDING_TITLES } from "@/lib/compare-dashboard";
import { hasPersistentFindings } from "@/lib/findings";
import type { PostAccountFindings } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Значок аккаунтных находок у поста, как у вуза на сравнении: красный —
 *  есть устойчивая находка, янтарный — только обычные. Подсказка — виды. */
export function AccountFindingsFlag({ findings }: { findings: PostAccountFindings }) {
  if (!findings.length) return null;
  const persistent = hasPersistentFindings({ accountFindings: findings });
  const note = "Находки аккаунта: " + findings
    .map((item) => FINDING_TITLES[item.kind] + (item.status === 2 ? " (устойчиво)" : "")).join("; ");
  return <span data-testid="findings-account-flag" role="img" aria-label={note} title={note}
    className={cn("inline-flex shrink-0", persistent ? "text-destructive" : "text-amber-600 dark:text-amber-400")}>
    <Flag className="size-3.5" aria-hidden="true" />
  </span>;
}
