import Link from "next/link";
import type { ReactNode } from "react";
import { formatDate, formatMetric, PLATFORM_LABELS } from "@/lib/format";
import { metricNumber, queryHref } from "@/lib/params";
import type { OverviewItem, OverviewMetric } from "@/lib/types";

function accountName(item: OverviewItem): string {
  const account = item.accounts[0];
  if (!account) return "Официальный аккаунт не добавлен";
  if (account.username) return `@${account.username}`;
  return account.title || account.canonicalExternalId;
}

function statusText(item: OverviewItem): string {
  if (item.lastErrorCode) return item.lastErrorCode;
  switch (item.statusCode) {
    case "no_account":
      return item.platform === "all"
        ? "Официальные аккаунты пока не подтверждены"
        : "Официальный аккаунт не добавлен";
    case "all_accounts_disabled":
      return "Сбор отключён";
    case "last_poll_failed":
      return "Последний опрос завершился с ошибкой";
    case "awaiting_first_poll":
      return "Опрос ещё не выполнялся";
    case "connected":
      return `Подключено ${item.connectedPlatformCount}/4 площадок`;
    default:
      return "активен";
  }
}

function Trend({ value }: { value: OverviewMetric["totalTrend"] }) {
  const numeric = metricNumber(value);
  if (numeric === null || numeric === 0) return <span className="trend-slot" />;
  return (
    <span className="trend-slot">
      <em className={`trend ${numeric > 0 ? "up" : "down"}`}>
        {numeric > 0 ? "+" : ""}{formatMetric(numeric)} к прошлому периоду
      </em>
    </span>
  );
}

function MetricCell({ value, label, trend }: {
  value: OverviewMetric["total"];
  label: string;
  trend: OverviewMetric["totalTrend"];
}) {
  return (
    <span className="legacy-metric-cell">
      <b className="metric-value">{formatMetric(value)}</b>
      <small>{label}</small>
      <Trend value={trend} />
    </span>
  );
}

function ActivityBody({ item }: { item: OverviewItem }) {
  return (
    <>
      <div className="card-head legacy-card-head">
        <div>
          <h2>{item.shortName || item.canonicalName}</h2>
          <p className="card-subtitle">{accountName(item)} · {formatMetric(item.subscriberCount)} подписчиков</p>
        </div>
        {item.ratingRank ? <span className="pill pill-blue">М‑Рейтинг {PLATFORM_LABELS[item.platform]} · №{item.ratingRank}</span> : null}
      </div>
      <div className="publication-badges" aria-label="Публикации за период">
        <span title="Всего публикаций в базе"><b>{formatMetric(item.totalPublicationCount)}</b><small>всего</small></span>
        <span className="activity" title="Публикации с измеримой активностью"><b>{formatMetric(item.activityPublicationCount)}</b><small>активных</small></span>
        <span className="new" title="Новые публикации"><b>{formatMetric(item.newPublicationCount)}</b><small>новых</small></span>
      </div>
      <div className="legacy-metrics-grid">
        <MetricCell value={item.reactions.total} label="реакций за период" trend={item.reactions.totalTrend} />
        <MetricCell value={item.views.total} label="просмотров за период" trend={item.views.totalTrend} />
        <MetricCell value={item.reactions.median} label="медиана прироста реакций" trend={item.reactions.medianTrend} />
        <MetricCell value={item.views.median} label="медиана прироста просмотров" trend={item.views.medianTrend} />
      </div>
      <div className="legacy-overview-footer">
        <div className={item.lastErrorCode ? "status-bad" : "status-ok"}>{statusText(item)}</div>
        <div className="muted">Последний опрос: {item.lastCheckedAt ? formatDate(item.lastCheckedAt) : "ещё не выполнялся"}</div>
      </div>
    </>
  );
}

function AllPlatformsBody({ item }: { item: OverviewItem }) {
  return (
    <>
      <div className="card-head legacy-card-head">
        <h2>{item.shortName || item.canonicalName}</h2>
        {item.ratingRank ? <span className="pill pill-blue">М‑Рейтинг · №{item.ratingRank}</span> : null}
      </div>
      {item.accounts.length ? (
        <div className="platform-account-list">
          {item.accounts.map((account) => {
            const name = account.title || account.username || account.canonicalExternalId;
            return (
              <div className="platform-account-line" key={account.accountId}>
                <span className={`platform-chip platform-${account.platform}`}>{PLATFORM_LABELS[account.platform]}</span>
                {account.url ? <a href={account.url} target="_blank" rel="noopener noreferrer">{name}</a> : <span>{name}</span>}
              </div>
            );
          })}
        </div>
      ) : <div className="platform-empty">Официальные аккаунты пока не подтверждены.</div>}
      <div className="platform-card-summary">
        <span><b className="metric-value">{item.connectedPlatformCount}/4</b><small>площадок подключено</small></span>
        <span><b className="metric-value">{item.accountCount}</b><small>аккаунтов добавлено</small></span>
      </div>
      <div className="legacy-overview-footer">
        <div className={item.lastErrorCode ? "status-bad" : "status-ok"}>{statusText(item)}</div>
      </div>
    </>
  );
}

function activityHref(item: OverviewItem): string {
  if (item.platform === "telegram") {
    return item.legacyRoute || `/channels/${item.legacyId}`;
  }
  if (item.accountCount === 1 && item.accounts[0]?.legacyId) {
    return item.accounts[0].legacyRoute || `/platform-accounts/${item.accounts[0].legacyId}`;
  }
  return queryHref(item.legacyRoute || `/institutions/${item.institutionLegacyId}`, {
    platform: item.platform,
  });
}

export function OverviewCard({ item }: { item: OverviewItem }) {
  const body: ReactNode = item.platform === "all"
    ? <AllPlatformsBody item={item} />
    : <ActivityBody item={item} />;
  if (item.platform === "all") {
    return <article className="panel overview-card legacy-overview-card">{body}</article>;
  }
  return <Link className="panel overview-card legacy-overview-card overview-card-link" href={activityHref(item)}>{body}</Link>;
}
