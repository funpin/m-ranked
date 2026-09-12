import Link from "@/components/native-link";
import type { ReactNode } from "react";
import { AlertCircle } from "lucide-react";
import { formatCoverage, formatDate, qualityLabel } from "@/lib/format";
import { metricEvidence, type AggregateMetric } from "@/lib/metric-evidence";
import { AnimatedNumber } from "@/components/animated-number";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { metricNumber } from "@/lib/params";
import type { Metrics, MetricValue } from "@/lib/types";

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
    <header className="mb-7">
      {eyebrow ? <p className="text-muted-foreground mb-1 text-[11px] font-semibold tracking-wide uppercase">{eyebrow}</p> : null}
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="font-heading text-3xl leading-tight font-bold tracking-tight text-balance">{title}</h1>
          <p className="text-muted-foreground mt-2 max-w-3xl text-base text-pretty">{description}</p>
        </div>
        {meta ? <div className="shrink-0">{meta}</div> : null}
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
  className,
}: {
  label: string;
  value: MetricValue;
  hint?: string;
  fraction?: boolean;
  evidence?: AggregateMetric;
  className?: string;
}) {
  const evidenceText = metricEvidence(evidence);
  return (
    <div className={cn("grid min-w-0 gap-0.5", className)} title={evidenceText}>
      <strong className="font-heading tabular text-[27px] leading-none font-extrabold tracking-tight">
        <AnimatedNumber value={metricNumber(value)} fraction={fraction} />
      </strong>
      <span className="text-muted-foreground text-[11px] leading-snug font-medium tracking-wide uppercase">{label}</span>
      {hint ? <span className="text-muted-foreground text-[11px] leading-snug">{hint}</span> : null}
      {evidenceText ? <span className="sr-only">{evidenceText}</span> : null}
    </div>
  );
}

export function AggregateMetrics({ metrics }: { metrics: Metrics }) {
  return (
    <div className="my-4 grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-5">
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
  const entries: [string, ReactNode][] = [
    ["Качество", qualityLabel(quality)],
    ["Выборка", `${sampleSize} публикаций`],
    ["Покрытие", formatCoverage(coverage)],
    ["Актуальность", formatDate(asOf)],
  ];
  if (revision !== undefined) entries.push(["Ревизия", `#${revision}`]);
  return (
    <dl className="flex flex-wrap gap-x-6 gap-y-3">
      {entries.map(([term, value]) => (
        <div key={term} className="grid gap-0.5">
          <dt className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">{term}</dt>
          <dd className="m-0 text-sm font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

const PILL_TONES = {
  blue: "border-transparent bg-chart-2/12 text-chart-2",
  green: "border-transparent bg-chart-1/12 text-chart-1",
  amber: "border-transparent bg-chart-3/15 text-chart-3",
  red: "border-transparent bg-destructive/12 text-destructive",
  neutral: "border-transparent bg-muted text-muted-foreground",
} as const;

export function StatusPill({ children, tone = "blue" }: {
  children: ReactNode;
  tone?: keyof typeof PILL_TONES;
}) {
  return <Badge className={cn("rounded-full font-bold", PILL_TONES[tone])}>{children}</Badge>;
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
    <Card aria-live="polite" className="my-5">
      <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
        <span className="text-muted-foreground text-2xl" aria-hidden="true">—</span>
        <h2 className="font-heading text-lg font-semibold">{title}</h2>
        <p className="text-muted-foreground max-w-prose text-pretty">{description}</p>
        {action ? (
          <Button render={<Link href={action.href} prefetch={false} />} variant="outline" className="mt-1">
            {action.label}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function ApiFailureState({ retryHref = "/" }: { retryHref?: string }) {
  return (
    <Card role="alert" className="my-5 border-destructive/30">
      <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
        <StatusPill tone="red">Сервис временно недоступен</StatusPill>
        <h2 className="font-heading text-lg font-semibold">Не удалось загрузить данные</h2>
        <p className="text-muted-foreground">Повторите попытку через некоторое время.</p>
        <Button render={<Link href={retryHref} prefetch={false} />} className="mt-1">
          Повторить
        </Button>
      </CardContent>
    </Card>
  );
}

export function InfoNotice({ children, tone = "blue" }: {
  children: ReactNode;
  tone?: "blue" | "amber";
}) {
  return (
    <aside
      className={cn(
        "my-4 flex gap-3 rounded-lg border-l-[3px] px-4 py-3 text-sm",
        tone === "amber" ? "border-l-chart-3 bg-chart-3/8" : "border-l-chart-2 bg-chart-2/8",
      )}
    >
      <AlertCircle className={cn("mt-0.5 size-4 shrink-0", tone === "amber" ? "text-chart-3" : "text-chart-2")} aria-hidden="true" />
      <div className="min-w-0 [&_b]:font-semibold">{children}</div>
    </aside>
  );
}
