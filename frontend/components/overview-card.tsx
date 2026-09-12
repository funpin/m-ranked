import { accountHref } from "@/lib/entity-routes";
import Link from "@/components/native-link";
import type { ReactNode } from "react";
import { ExternalLink, FileText, Plus, TrendingUp } from "lucide-react";
import { legacyDate, legacyNumber, PERIOD_SHORT, PLATFORM_LABELS } from "@/lib/format";
import { metricNumber, queryHref } from "@/lib/params";
import type { OverviewItem, OverviewMetric, OverviewPage } from "@/lib/types";
import { overviewStatus } from "@/lib/overview-status";
import { metricEvidence, type AggregateMetric } from "@/lib/metric-evidence";
import { AnimatedNumber } from "@/components/animated-number";
import { cn } from "@/lib/utils";

function accountName(item: OverviewItem): string {
  const account = item.accounts[0];
  if (!account) return "Официальный аккаунт не добавлен";
  if (account.username) return `@${account.username}`;
  return account.title || account.canonicalExternalId;
}

/** The slot keeps its height whether or not there is a change to report, so a
 *  grid of cards does not shift as values load. */
function Trend({ value, suffix }: { value: OverviewMetric["totalTrend"]; suffix:string }) {
  const numeric = metricNumber(value);
  if (numeric === null || numeric === 0) return <span className="block min-h-[22px]" />;
  return (
    <span className="block min-h-[22px]">
      <span className={cn(
        "mt-1 inline-block w-max max-w-full rounded-full px-2 py-0.5 text-[10px] font-extrabold tabular",
        numeric > 0 ? "bg-success/12 text-success" : "bg-destructive/12 text-destructive",
      )}>
        {numeric > 0 ? "+" : ""}{legacyNumber(numeric)} {suffix}
      </span>
    </span>
  );
}

function MetricCell({ value, label, trend, evidence, suffix }: {
  value: OverviewMetric["total"];
  label: string;
  trend: OverviewMetric["totalTrend"];
  evidence: AggregateMetric;
  suffix:string;
}) {
  const text = metricEvidence(evidence);
  return (
    <span className="grid min-w-0 cursor-help content-start" tabIndex={0} title={text}>
      <b className="font-heading tabular text-[27px] leading-none font-extrabold tracking-tight">
        <AnimatedNumber value={metricNumber(value)} />
      </b>
      <small className="text-muted-foreground mt-1 min-h-[2.7em] text-[10px] leading-snug font-medium tracking-wide uppercase">{label} ⓘ</small>
      <Trend value={trend} suffix={suffix} />
      <span className="sr-only">{text}</span>
    </span>
  );
}

function ActivityBody({ item, integrationWarning }: { item: OverviewItem; integrationWarning: OverviewPage["integrationWarning"] }) {
  const short = PERIOD_SHORT[item.period];
  const primary = item.platform === "vk" || item.platform === "rutube" ? "лайков" : "реакций";
  const suffix=short;
  const status=overviewStatus(item,integrationWarning);
  const badges = <div className="mt-3 flex flex-wrap gap-1.5" aria-label={`Публикации ${short}`}>
    {[
      { label: "Всего публикаций в базе.", value: item.totalPublicationCount, Icon: FileText, tone: "bg-muted text-muted-foreground", kind: "" },
      { label: `Публикации из БД с активностью ${short}.`, value: item.activityPublicationCount, Icon: TrendingUp, tone: "bg-chart-2/12 text-chart-2", kind: "activity" },
      { label: `Публикации, вышедшие ${short}.`, value: item.newPublicationCount, Icon: Plus, tone: "bg-success/12 text-success", kind: "new" },
    ].map(({ label, value, Icon, tone, kind }) => (
      <span key={kind} className={cn("inline-flex cursor-help items-center gap-1 rounded-md px-1.5 py-1 text-xs font-bold tabular", tone)} tabIndex={0} title={label} aria-label={`${label} ${value}`}>
        <Icon className="size-3.5 shrink-0" aria-hidden="true" /><b>{value}</b>
      </span>
    ))}
  </div>;
  return <>
    {item.ratingRank ? <span className="bg-chart-2/12 text-chart-2 absolute -top-2.5 -right-1.5 z-[3] cursor-help rounded-full px-2 py-1 text-[10px] font-extrabold whitespace-nowrap shadow-sm" tabIndex={0} title={`Официальное место в М‑Рейтинге ${PLATFORM_LABELS[item.platform]}.`}>М‑Рейтинг {PLATFORM_LABELS[item.platform]} · №{item.ratingRank}</span> : null}
    <div className="min-h-[116px]">
      <h3 className="font-heading line-clamp-2 min-h-[2.7em] cursor-help text-base leading-snug font-bold" tabIndex={0} title={item.canonicalName}>
        {item.shortName || item.canonicalName}<span className="text-muted-foreground ml-1 text-xs" aria-hidden="true">ⓘ</span>
      </h3>
      <div className="text-muted-foreground mt-1 truncate text-xs">{accountName(item)}{item.accounts.length ? <> · {legacyNumber(item.subscriberCount)} подписчиков{item.accountCount > 1 ? ` · ещё ${item.accountCount - 1}` : ""}</> : null}</div>
      {item.platform === "telegram" ? badges : null}
    </div>
    {item.platform !== "telegram" ? badges : null}
    <div className="my-4 grid flex-1 grid-cols-2 content-center gap-x-5 gap-y-3">
      <MetricCell suffix={suffix} value={item.reactions.total} label={`${primary} ${short}`} trend={item.reactions.totalTrend} evidence={item.reactions.totalMetadata} />
      <MetricCell suffix={suffix} value={item.views.total} label={`просмотров ${short}`} trend={item.views.totalTrend} evidence={item.views.totalMetadata} />
      <MetricCell suffix={suffix} value={item.reactions.median} label={`медиана прироста ${primary}`} trend={item.reactions.medianTrend} evidence={item.reactions.medianMetadata} />
      <MetricCell suffix={suffix} value={item.views.median} label="медиана прироста просмотров" trend={item.views.medianTrend} evidence={item.views.medianMetadata} />
    </div>
    <div className="border-border mt-auto min-h-[67px] border-t pt-3.5">
      <div className={cn("font-semibold", status.kind === "ok" ? "text-success" : status.kind === "warn" ? "text-warning" : status.kind === "bad" ? "text-destructive" : "text-muted-foreground")}>{status.text}</div>
      <div className="text-muted-foreground mt-0.5 text-xs">Последний опрос: {item.lastCheckedAt ? legacyDate(item.lastCheckedAt, true) : "ещё не выполнялся"}</div>
    </div>
  </>;
}

function AllPlatformsBody({ item }: { item: OverviewItem }) {
  const status=overviewStatus(item);
  return (
    <>
      {item.ratingRank ? <span className="bg-chart-2/12 text-chart-2 absolute -top-2.5 -right-1.5 z-[3] cursor-help rounded-full px-2 py-1 text-[10px] font-extrabold whitespace-nowrap shadow-sm" tabIndex={0} title="Официальное место в М‑Рейтинге: Общий.">М‑Рейтинг Общий · №{item.ratingRank}</span> : null}
      <div>
        <h3 className="font-heading line-clamp-2 min-h-[2.7em] cursor-help text-base leading-snug font-bold" tabIndex={0} title={item.canonicalName}>
          {item.shortName || item.canonicalName}<span className="text-muted-foreground ml-1 text-xs" aria-hidden="true">ⓘ</span>
        </h3>
      </div>
      {item.accounts.length ? (
        <div className="my-4 grid gap-1.5">
          {[...item.accounts].sort((a,b)=>a.platform.localeCompare(b.platform)).map((account) => {
            const name = account.title || account.username || account.canonicalExternalId;
            return (
              <div className="bg-muted/60 flex min-w-0 items-center gap-2 rounded-md px-2 py-2" key={account.accountId}>
                <span className="bg-chart-2/12 text-chart-2 inline-block min-w-[66px] rounded-md px-1.5 py-0.5 text-center text-[11px] font-black">{PLATFORM_LABELS[account.platform]}</span>
                {account.url
                  ? <a className="text-chart-2 inline-flex min-w-0 items-center gap-1 truncate hover:underline" href={account.url} target="_blank" rel="noopener noreferrer">{name}<ExternalLink className="size-3.5 shrink-0" aria-hidden="true" /></a>
                  : <span className="min-w-0 truncate">{name}</span>}
              </div>
            );
          })}
        </div>
      ) : <div className="text-muted-foreground py-4">Официальный аккаунт этой площадки пока не подтверждён.</div>}
      <div className="my-3.5 grid grid-cols-2 gap-3">
        <span className="grid min-w-0 gap-0.5"><b className="font-heading tabular text-[27px] leading-none font-extrabold tracking-tight">{item.connectedPlatformCount}/4</b><small className="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">площадок подключено</small></span>
        <span className="grid min-w-0 gap-0.5"><b className="font-heading tabular text-[27px] leading-none font-extrabold tracking-tight">{item.accountCount}</b><small className="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">аккаунтов добавлено</small></span>
      </div>
      <div className="border-border mt-auto min-h-[67px] border-t pt-3.5">
        <div className={cn("font-semibold", status.kind === "ok" ? "text-success" : status.kind === "warn" ? "text-warning" : status.kind === "bad" ? "text-destructive" : "text-muted-foreground")}>{status.text}</div>
      </div>
    </>
  );
}

function activityHref(item: OverviewItem): string {
  if (item.platform === "telegram") {
    return accountHref(item.entityId);
  }
  if (item.accountCount === 1 && item.accounts[0]?.accountId) {
    return accountHref(item.accounts[0].accountId);
  }
  return queryHref(item.legacyRoute || `/institutions/${item.institutionLegacyId}`, {
    platform: item.platform,
  });
}

const CARD = "bg-card text-card-foreground relative z-[1] flex min-h-[470px] min-w-0 flex-col rounded-xl border p-5 pt-6 shadow-sm transition-[transform,box-shadow] duration-200";

export function OverviewCard({ item, integrationWarning }: { item: OverviewItem; integrationWarning: OverviewPage["integrationWarning"] }) {
  const body: ReactNode = item.platform === "all"
    ? <AllPlatformsBody item={item} />
    : <ActivityBody item={item} integrationWarning={integrationWarning} />;
  if (item.platform === "all") {
    return <article data-testid="platform-overview-card" className={cn(CARD, "min-h-[310px]")}>{body}</article>;
  }
  return (
    <Link
      className={cn(CARD, "hover:border-ring/40 no-underline hover:z-30 hover:-translate-y-0.5 hover:shadow-lg hover:no-underline focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none")}
      href={activityHref(item)}
      prefetch={false}
    >
      {body}
    </Link>
  );
}
