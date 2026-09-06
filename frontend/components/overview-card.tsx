import { accountHref } from "@/lib/entity-routes";
import Link from "next/link";
import type { ReactNode } from "react";
import { legacyDate, legacyNumber, PERIOD_SHORT, PLATFORM_LABELS } from "@/lib/format";
import { metricNumber, queryHref } from "@/lib/params";
import type { OverviewItem, OverviewMetric, OverviewPage } from "@/lib/types";
import { overviewStatus } from "@/lib/overview-status";
import { metricEvidence, type AggregateMetric } from "@/lib/metric-evidence";

function accountName(item: OverviewItem): string {
  const account = item.accounts[0];
  if (!account) return "Официальный аккаунт не добавлен";
  if (account.username) return `@${account.username}`;
  return account.title || account.canonicalExternalId;
}

function Trend({ value, suffix }: { value: OverviewMetric["totalTrend"]; suffix:string }) {
  const numeric = metricNumber(value);
  if (numeric === null || numeric === 0) return <span className="trend-slot" />;
  return (
    <span className="trend-slot">
      <em className={`trend ${numeric > 0 ? "up" : "down"}`}>
        {numeric > 0 ? "+" : ""}{legacyNumber(numeric)} {suffix}
      </em>
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
  return (
    <span className="has-tooltip" tabIndex={0} data-tooltip={metricEvidence(evidence)} title={metricEvidence(evidence)}>
      <b className="metric">{legacyNumber(value)}</b>
      <small>{label} ⓘ</small>
      <Trend value={trend} suffix={suffix} />
      <span className="sr-only">{metricEvidence(evidence)}</span>
    </span>
  );
}

function ActivityBody({ item, integrationWarning }: { item: OverviewItem; integrationWarning: OverviewPage["integrationWarning"] }) {
  const short = PERIOD_SHORT[item.period];
  const primary = item.platform === "vk" || item.platform === "rutube" ? "лайков" : "реакций";
  const suffix=short;
  const status=overviewStatus(item,integrationWarning);
  const badges = <div className="post-stat-badges" aria-label={`Публикации ${short}`}>
    {[
      { label: "Всего публикаций в базе.", value: item.totalPublicationCount, path: "M6 4h12v16H6zM9 8h6M9 12h6M9 16h4", kind: "" },
      { label: `Публикации из БД с активностью ${short}.`, value: item.activityPublicationCount, path: "M4 17l5-5 4 3 7-8M16 7h4v4", kind: "activity" },
      { label: `Публикации, вышедшие ${short}.`, value: item.newPublicationCount, path: "M12 3v18M3 12h18", kind: "new" },
    ].map((badge) => <span key={badge.kind} className={`post-stat-badge has-tooltip ${badge.kind}`} tabIndex={0} data-tooltip={badge.label} aria-label={`${badge.label} ${badge.value}`}>
      <svg aria-hidden="true" viewBox="0 0 24 24"><path d={badge.path} /></svg><b>{badge.value}</b>
    </span>)}
  </div>;
  return <>
    {item.ratingRank ? <span className="m-rating-badge has-tooltip" tabIndex={0} data-tooltip={`Официальное место в М‑Рейтинге ${PLATFORM_LABELS[item.platform]}.`}>М‑Рейтинг {PLATFORM_LABELS[item.platform]} · №{item.ratingRank}</span> : null}
    <div className="overview-header">
      <div className="card-title-row"><h3 className="institution-title has-tooltip" tabIndex={0} data-tooltip={item.canonicalName}><span className="title-text">{item.shortName || item.canonicalName}</span><span className="title-info info-mark" aria-hidden="true">ⓘ</span></h3></div>
      <div className="muted channel-meta">{accountName(item)}{item.accounts.length ? <> · {legacyNumber(item.subscriberCount)} подписчиков{item.accountCount > 1 ? ` · ещё ${item.accountCount - 1}` : ""}</> : null}</div>
      {item.platform === "telegram" ? badges : null}
    </div>
    {item.platform !== "telegram" ? badges : null}
    <div className="metrics overview-metrics">
      <MetricCell suffix={suffix} value={item.reactions.total} label={`${primary} ${short}`} trend={item.reactions.totalTrend} evidence={item.reactions.totalMetadata} />
      <MetricCell suffix={suffix} value={item.views.total} label={`просмотров ${short}`} trend={item.views.totalTrend} evidence={item.views.totalMetadata} />
      <MetricCell suffix={suffix} value={item.reactions.median} label={`медиана прироста ${primary}`} trend={item.reactions.medianTrend} evidence={item.reactions.medianMetadata} />
      <MetricCell suffix={suffix} value={item.views.median} label="медиана прироста просмотров" trend={item.views.medianTrend} evidence={item.views.medianMetadata} />
    </div>
    <div className="overview-footer">
      <div className={status.kind}>{status.text}</div>
      <div className="muted">Последний опрос: {item.lastCheckedAt ? legacyDate(item.lastCheckedAt, true) : "ещё не выполнялся"}</div>
    </div>
  </>;
}

function AllPlatformsBody({ item }: { item: OverviewItem }) {
  const status=overviewStatus(item);
  return (
    <>
      {item.ratingRank ? <span className="m-rating-badge has-tooltip" tabIndex={0} data-tooltip={`Официальное место в М‑Рейтинге: Общий.`}>М‑Рейтинг Общий · №{item.ratingRank}</span> : null}
      <div className="overview-header"><div className="card-title-row"><h3 className="institution-title has-tooltip" tabIndex={0} data-tooltip={item.canonicalName}><span className="title-text">{item.shortName || item.canonicalName}</span><span className="title-info info-mark" aria-hidden="true">ⓘ</span></h3></div></div>
      {item.accounts.length ? (
        <div className="platform-card-accounts">
          {[...item.accounts].sort((a,b)=>a.platform.localeCompare(b.platform)).map((account) => {
            const name = account.title || account.username || account.canonicalExternalId;
            return (
              <div className="platform-account-line" key={account.accountId}>
                <span className={`platform-chip platform-${account.platform}`}>{PLATFORM_LABELS[account.platform]}</span>
                {account.url ? <a className="external" href={account.url} target="_blank" rel="noopener noreferrer">{name}</a> : <span>{name}</span>}
              </div>
            );
          })}
        </div>
      ) : <div className="platform-empty">Официальный аккаунт этой площадки пока не подтверждён.</div>}
      <div className="platform-card-summary">
        <span><b className="metric">{item.connectedPlatformCount}/4</b><small>площадок подключено</small></span>
        <span><b className="metric">{item.accountCount}</b><small>аккаунтов добавлено</small></span>
      </div>
      <div className="overview-footer">
        <div className={status.kind}>{status.text}</div>
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

export function OverviewCard({ item, integrationWarning }: { item: OverviewItem; integrationWarning: OverviewPage["integrationWarning"] }) {
  const body: ReactNode = item.platform === "all"
    ? <AllPlatformsBody item={item} />
    : <ActivityBody item={item} integrationWarning={integrationWarning} />;
  if (item.platform === "all") {
    return <article className="card overview-card platform-overview-card">{body}</article>;
  }
  return <Link className="card overview-card" href={activityHref(item)}>{body}</Link>;
}
