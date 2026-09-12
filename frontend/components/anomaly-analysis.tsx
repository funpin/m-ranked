import { legacyDate } from "@/lib/format";
import type { PublicationAnomalyAnalysis } from "@/lib/types";
import { StatusPill } from "@/components/ui";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChevronRight } from "lucide-react";

const SOURCE_REVISION_FLOOR=1_000_000_000_000;
const statusLabels = { pending:"ожидает анализа",ready:"готов",partial:"частичное покрытие",stale:"устарел после ошибки",failed:"ошибка анализа" } as const;
const statusTones = { pending:"neutral",ready:"green",partial:"amber",stale:"amber",failed:"red" } as const;
const severityLabels = { low:"низкая",medium:"средняя",high:"высокая" } as const;
const reviewLabels = { unreviewed:"не проверен",explained:"объяснён",unresolved:"требует проверки",data_error:"ошибка данных",dismissed:"отклонён" } as const;
const metricLabels = { views:"просмотры",reactions:"реакции",comments:"комментарии",shares:"репосты" } as const;

function Warning({ children }: { children: React.ReactNode }) {
  return <p className="border-l-chart-3 bg-chart-3/8 text-foreground rounded-r-md border-l-[3px] px-3 py-2.5">{children}</p>;
}

export function AnomalyAnalysis({analysis,loadFailed,historyRevision}:{analysis:PublicationAnomalyAnalysis|null;loadFailed:boolean;historyRevision:number}) {
  if(loadFailed) return (
    <Card as="section" className="my-4" aria-labelledby="anomaly-title">
      <CardHeader><CardTitle as="h2" id="anomaly-title" className="font-heading text-lg">Сигнал аномальной динамики</CardTitle></CardHeader>
      <CardContent><Warning>Результат анализа временно недоступен. Это техническая ошибка, а не чистый результат.</Warning></CardContent>
    </Card>
  );
  if(!analysis) return null;
  // Source-backed revisions are epoch-millis watermarks (DatasetRevision.SOURCE_ID_FLOOR),
  // not comparable with the projection revision the worker pinned.
  const comparableRevision=historyRevision<SOURCE_REVISION_FLOOR;
  const staleEvidence=comparableRevision && analysis.sourceDatasetRevision!==null && analysis.sourceDatasetRevision<historyRevision;
  return (
    <Card as="section" className="my-4" aria-labelledby="anomaly-title">
      <CardHeader className="flex flex-wrap items-start justify-between gap-4">
        <CardTitle as="h2" id="anomaly-title" className="font-heading text-lg">Сигнал аномальной динамики</CardTitle>
        <StatusPill tone={statusTones[analysis.status]}>{statusLabels[analysis.status]}</StatusPill>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p>{analysis.suspicionScore===null ? "Автоматическая оценка: недостаточно применимых данных" : <>Эвристическая сила сигнала: <b className="tabular font-semibold">{Number(analysis.suspicionScore).toFixed(2)}</b>{analysis.overallSeverity ? ` · выраженность: ${severityLabels[analysis.overallSeverity]}` : ""}</>}</p>
        {analysis.affectedMetrics.length ? <p>Затронутые показатели: {analysis.affectedMetrics.map(metric=>metricLabels[metric]).join(", ")}.</p> : null}
        {analysis.manualAssessmentPresent ? <p><b className="font-semibold">Присутствует отдельная ручная оценка.</b> Она не включена в автоматический числовой балл.</p> : null}
        {analysis.status==="pending" ? <p className="text-muted-foreground">Исторические наблюдения ещё не были обработаны анализатором.</p> : null}
        {analysis.status==="stale"||analysis.status==="failed" ? <Warning>Последняя попытка завершилась технической ошибкой{analysis.status==="stale" ? "; показан предыдущий успешный результат" : ""}.</Warning> : null}
        {staleEvidence ? <Warning>Сигналы рассчитаны по более ранней ревизии данных. Интервалы показаны по исходным временным границам и не привязываются к ближайшим новым точкам.</Warning> : null}
        {analysis.analyzedAt ? <p className="text-muted-foreground text-sm">Проанализировано: {legacyDate(analysis.analyzedAt,true)} · ревизия анализа {analysis.analysisRevision} · источник {analysis.sourceDatasetRevision ?? "—"}</p> : null}
        {analysis.findings.length ? (
          <div className="grid gap-2">
            {analysis.findings.map(finding => (
              <details key={finding.id} className="border-border bg-muted/40 group rounded-lg border px-3 py-2.5">
                <summary className="flex cursor-pointer items-center gap-2 marker:content-none">
                  <ChevronRight className="size-4 shrink-0 transition-transform group-open:rotate-90" aria-hidden="true" />
                  <span><b className="font-semibold">{metricLabels[finding.metric]}</b> · {severityLabels[finding.severity]} · {reviewLabels[finding.reviewState]}</span>
                </summary>
                <dl className="my-3 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1.5 text-sm">
                  <dt className="text-muted-foreground">Интервал наблюдения</dt>
                  <dd className="m-0 tabular">{legacyDate(finding.suspiciousStartAt,true)} — {legacyDate(finding.suspiciousEndAt,true)}</dd>
                  <dt className="text-muted-foreground">Основание</dt>
                  <dd className="m-0">{finding.explanationCode}</dd>
                </dl>
                {finding.qualityCodes.length ? <p className="text-sm">Ограничения качества: {finding.qualityCodes.join(", ")}.</p> : null}
                {finding.alternativeExplanationCodes.length ? <p className="text-sm">Возможные альтернативные объяснения: {finding.alternativeExplanationCodes.join(", ")}.</p> : null}
              </details>
            ))}
          </div>
        ) : <p className="text-muted-foreground">Активных сигналов нет.</p>}
        <p className="text-muted-foreground text-sm">{analysis.disclaimer} Балл является версионированной эвристической оценкой силы сигнала, а не вероятностью.</p>
      </CardContent>
    </Card>
  );
}
