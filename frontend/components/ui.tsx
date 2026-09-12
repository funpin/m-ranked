import Link from "@/components/native-link";
import type { ReactNode } from "react";
import { formatCoverage, formatDate, formatMetric, qualityLabel } from "@/lib/format";
import type { Metrics, MetricValue } from "@/lib/types";
import { metricEvidence, type AggregateMetric } from "@/lib/metric-evidence";

export function PageHeader({
  eyebrow,
  title,
  description,
  meta,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  meta?: ReactNode;
}) {
  return (
    <header className="page-heading">
      {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
      <div className="heading-row">
        <div>
          <h1>{title}</h1>
          <p className="lead">{description}</p>
        </div>
        {meta ? <div className="heading-meta">{meta}</div> : null}
      </div>
    </header>
  );
}

export function Metric({
  label,
  value,
  hint,
  fraction = false,
  evidence,
}: {
  label: string;
  value: MetricValue;
  hint?: string;
  fraction?: boolean;
  evidence?: AggregateMetric;
}) {
  return (
    <div className="metric-block" title={metricEvidence(evidence)}>
      <strong className="metric-value">{formatMetric(value, fraction)}</strong>
      <span className="metric-label">{label}</span>
      {hint ? <span className="metric-hint">{hint}</span> : null}
      {evidence ? <span className="sr-only">{metricEvidence(evidence)}</span> : null}
    </div>
  );
}

export function AggregateMetrics({ metrics }: { metrics: Metrics }) {
  return (
    <div className="metrics-grid">
      <Metric label="реакций за период" value={metrics.totalReactions} evidence={metrics.aggregates.totalReactions} />
      <Metric label="просмотров за период" value={metrics.totalViews} evidence={metrics.aggregates.totalViews} />
      <Metric label="медиана реакций" value={metrics.medianReactions} evidence={metrics.aggregates.medianReactions} fraction />
      <Metric label="медиана просмотров" value={metrics.medianViews} evidence={metrics.aggregates.medianViews} fraction />
    </div>
  );
}

export function DataProvenance({
  quality,
  sampleSize,
  coverage,
  asOf,
  revision,
}: {
  quality: string | null;
  sampleSize: number;
  coverage: MetricValue;
  asOf: string | null;
  revision?: number;
}) {
  return (
    <dl className="provenance">
      <div><dt>Качество</dt><dd>{qualityLabel(quality)}</dd></div>
      <div><dt>Выборка</dt><dd>{sampleSize} публикаций</dd></div>
      <div><dt>Покрытие</dt><dd>{formatCoverage(coverage)}</dd></div>
      <div><dt>Актуальность</dt><dd>{formatDate(asOf)}</dd></div>
      {revision === undefined ? null : <div><dt>Ревизия</dt><dd>#{revision}</dd></div>}
    </dl>
  );
}

export function StatusPill({ children, tone = "blue" }: {
  children: ReactNode;
  tone?: "blue" | "green" | "amber" | "red" | "neutral";
}) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: { href: string; label: string };
}) {
  return (
    <section className="panel empty-state" aria-live="polite">
      <span className="empty-icon" aria-hidden="true">—</span>
      <h2>{title}</h2>
      <p>{description}</p>
      {action ? <Link className="button-link secondary-button" href={action.href} prefetch={false}>{action.label}</Link> : null}
    </section>
  );
}

export function ApiFailureState({ retryHref = "/" }: { retryHref?: string }) {
  return (
    <section className="panel error-state" role="alert">
      <StatusPill tone="red">Сервис временно недоступен</StatusPill>
      <h2>Не удалось загрузить данные</h2>
      <p>Повторите попытку через некоторое время.</p>
      <Link className="button-link" href={retryHref} prefetch={false}>Повторить</Link>
    </section>
  );
}

export function InfoNotice({ children, tone = "blue" }: {
  children: ReactNode;
  tone?: "blue" | "amber";
}) {
  return <aside className={`notice notice-${tone}`}>{children}</aside>;
}
