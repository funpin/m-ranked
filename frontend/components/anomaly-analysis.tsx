import { legacyDate } from "@/lib/format";
import type { PublicationAnomalyAnalysis } from "@/lib/types";

const SOURCE_REVISION_FLOOR=1_000_000_000_000;
const statusLabels = { pending:"ожидает анализа",ready:"готов",partial:"частичное покрытие",stale:"устарел после ошибки",failed:"ошибка анализа" } as const;
const severityLabels = { low:"низкая",medium:"средняя",high:"высокая" } as const;
const reviewLabels = { unreviewed:"не проверен",explained:"объяснён",unresolved:"требует проверки",data_error:"ошибка данных",dismissed:"отклонён" } as const;
const metricLabels = { views:"просмотры",reactions:"реакции",comments:"комментарии",shares:"репосты" } as const;

export function AnomalyAnalysis({analysis,loadFailed,historyRevision}:{analysis:PublicationAnomalyAnalysis|null;loadFailed:boolean;historyRevision:number}) {
  if(loadFailed) return <section className="card anomaly-panel" aria-labelledby="anomaly-title"><h2 id="anomaly-title">Сигнал аномальной динамики</h2><p className="warning">Результат анализа временно недоступен. Это техническая ошибка, а не чистый результат.</p></section>;
  if(!analysis) return null;
  // Source-backed revisions are epoch-millis watermarks (DatasetRevision.SOURCE_ID_FLOOR),
  // not comparable with the projection revision the worker pinned.
  const comparableRevision=historyRevision<SOURCE_REVISION_FLOOR;
  const staleEvidence=comparableRevision && analysis.sourceDatasetRevision!==null && analysis.sourceDatasetRevision<historyRevision;
  return <section className="card anomaly-panel" aria-labelledby="anomaly-title">
    <div className="section-heading"><h2 id="anomaly-title">Сигнал аномальной динамики</h2><span className={`pill anomaly-${analysis.status}`}>{statusLabels[analysis.status]}</span></div>
    <p>{analysis.suspicionScore===null ? "Автоматическая оценка: недостаточно применимых данных" : <>Эвристическая сила сигнала: <b>{Number(analysis.suspicionScore).toFixed(2)}</b>{analysis.overallSeverity ? ` · выраженность: ${severityLabels[analysis.overallSeverity]}` : ""}</>}</p>
    {analysis.affectedMetrics.length ? <p>Затронутые показатели: {analysis.affectedMetrics.map(metric=>metricLabels[metric]).join(", ")}.</p> : null}
    {analysis.manualAssessmentPresent ? <p><b>Присутствует отдельная ручная оценка.</b> Она не включена в автоматический числовой балл.</p> : null}
    {analysis.status==="pending" ? <p className="muted">Исторические наблюдения ещё не были обработаны анализатором.</p> : null}
    {analysis.status==="stale"||analysis.status==="failed" ? <p className="warning">Последняя попытка завершилась технической ошибкой{analysis.status==="stale" ? "; показан предыдущий успешный результат" : ""}.</p> : null}
    {staleEvidence ? <p className="warning">Сигналы рассчитаны по более ранней ревизии данных. Интервалы показаны по исходным временным границам и не привязываются к ближайшим новым точкам.</p> : null}
    {analysis.analyzedAt ? <p className="muted">Проанализировано: {legacyDate(analysis.analyzedAt,true)} · ревизия анализа {analysis.analysisRevision} · источник {analysis.sourceDatasetRevision ?? "—"}</p> : null}
    {analysis.findings.length ? <div className="anomaly-findings">{analysis.findings.map(finding=><details key={finding.id}><summary><b>{metricLabels[finding.metric]}</b> · {severityLabels[finding.severity]} · {reviewLabels[finding.reviewState]}</summary>
      <dl><dt>Интервал наблюдения</dt><dd>{legacyDate(finding.suspiciousStartAt,true)} — {legacyDate(finding.suspiciousEndAt,true)}</dd><dt>Основание</dt><dd>{finding.explanationCode}</dd></dl>
      {finding.qualityCodes.length ? <p>Ограничения качества: {finding.qualityCodes.join(", ")}.</p> : null}
      {finding.alternativeExplanationCodes.length ? <p>Возможные альтернативные объяснения: {finding.alternativeExplanationCodes.join(", ")}.</p> : null}
    </details>)}</div> : <p className="muted">Активных сигналов нет.</p>}
    <p className="panel-note">{analysis.disclaimer} Балл является версионированной эвристической оценкой силы сигнала, а не вероятностью.</p>
  </section>;
}
