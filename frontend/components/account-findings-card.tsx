import { Suspense } from "react";
import { UsersRound } from "lucide-react";
import { Card } from "@/components/ui/card";
import { StatusPill } from "@/components/ui";
import { MethodNote } from "@/components/method-note";
import type { AccountAnomalyFindings } from "@/lib/types";

const METHOD = "Аккаунтная находка — закономерность, которую видно только на многих постах сразу: один пост с "
  + "небольшой аудиторией не даёт уверенного вывода, а месяц одинаковых постов даёт. Аккаунт сравнивается с "
  + "другими аккаунтами своей площадки за последние 30 дней. «Стартовый пакет» — доля реакций на просмотр в "
  + "первые два часа во много раз выше, чем за следующие сутки, у большинства постов. «Ровный отклик» — число "
  + "реакций почти не зависит от поста: разброс не больше случайного. «Устойчиво» — закономерность есть в обеих "
  + "половинах окна. Находки считаются отдельно и не меняют уровни постов; посты, из которых складывается "
  + "находка, ссылаются на неё.";

export type FindingsLoad = AccountAnomalyFindings | null;

/** Блок страницы аккаунта: появляется, только если находки есть. Пока ответ в
 *  пути, страница его не ждёт; сбой анализа — тишина, а не ошибка страницы. */
export function AccountFindingsCard({ findings }: { findings: Promise<FindingsLoad> }) {
  return <Suspense fallback={null}><Body findings={findings} /></Suspense>;
}

async function Body({ findings }: { findings: Promise<FindingsLoad> }) {
  const loaded = await findings;
  if (!loaded?.items.length) return null;
  return (
    <Card as="section" id="account-findings" className="mt-5 block min-w-0 scroll-mt-20 p-5 text-sm"
      data-testid="account-findings-card" aria-labelledby="account-findings-heading">
      <h2 id="account-findings-heading" className="font-heading flex flex-wrap items-center gap-1 text-lg font-semibold tracking-tight">
        Аккаунтные находки <MethodNote title="Аккаунтные находки">{METHOD}</MethodNote>
      </h2>
      <ul className="mt-3 grid gap-4">
        {loaded.items.map((finding) => (
          <li key={finding.kind} className="grid gap-2 rounded-lg border p-4" data-testid="account-finding" data-kind={finding.kind}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 font-semibold">
                <UsersRound className="text-chart-3 size-4 shrink-0" aria-hidden="true" />{finding.title}
              </span>
              {finding.statusLabel ? <StatusPill tone={finding.status === 2 ? "amber" : "neutral"}>{finding.statusLabel}</StatusPill> : null}
              <span className="text-muted-foreground text-xs tabular-nums">
                {period(finding.windowStart, finding.windowEnd)}
                {finding.membersCount ? ` · постов в находке: ${finding.membersCount}` : null}
              </span>
            </div>
            {finding.summary ? <p className="leading-relaxed">{finding.summary}.</p> : null}
            {finding.alternatives ? <p className="text-muted-foreground text-xs leading-relaxed">
              Другие объяснения: {finding.alternatives.replace(/^./, (letter) => letter.toLowerCase())}.
            </p> : null}
          </li>
        ))}
      </ul>
      <p className="text-muted-foreground mt-3 text-xs leading-relaxed">{loaded.disclaimer}</p>
    </Card>
  );
}

const shortDate = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", timeZone: "UTC" });

/** Окно находки: правая граница — первый день после окна. */
function period(start: string, end: string) {
  const last = new Date(end);
  last.setUTCDate(last.getUTCDate() - 1);
  return `${shortDate.format(new Date(start))} — ${shortDate.format(last)}`;
}
