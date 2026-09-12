import Link from "next/link";
import { InfoNotice, Metric, PageHeader, StatusPill } from "./ui";
import { formatDate, PLATFORM_LONG_LABELS } from "@/lib/format";
import type { AccountView } from "@/lib/types";

function safeExternalUrl(value: string | null): string | null {
  return value?.startsWith("https://") ? value : null;
}

export function AccountDetail({
  account,
  channelCompatibility = false,
}: {
  account: AccountView;
  channelCompatibility?: boolean;
}) {
  const institutionName = account.institutionShortName || account.institutionName;
  const accountName = account.title
    || (account.username ? `@${account.username}` : null)
    || institutionName;
  const externalUrl = safeExternalUrl(account.url);
  return (
    <>
      <nav className="breadcrumbs" aria-label="Хлебные крошки">
        <Link href="/">Обзор</Link>
        <span aria-hidden="true">/</span>
        <Link href={`/institutions/${account.institutionLegacyId}?platform=${account.platform}`}>
          {institutionName}
        </Link>
        <span aria-hidden="true">/</span>
        <span>{accountName}</span>
      </nav>
      <PageHeader
        eyebrow={`${PLATFORM_LONG_LABELS[account.platform]} · ${channelCompatibility ? "канал" : "аккаунт"}`}
        title={accountName}
        description={account.username ? `${account.institutionName} · @${account.username}` : account.institutionName}
        meta={<StatusPill tone={account.enabled ? "green" : "neutral"}>{account.enabled ? "активен" : "отключён"}</StatusPill>}
      />
      <section className="panel detail-panel">
        <div className="section-head">
          <div><p className="eyebrow">Сводка</p><h2>Состояние аккаунта</h2></div>
          <StatusPill tone="blue">ID {account.legacyId}</StatusPill>
        </div>
        <div className="metrics-grid">
          <Metric label="публикаций в проекции" value={account.publicationCount} />
        </div>
        <dl className="provenance account-provenance">
          <div><dt>Площадка</dt><dd>{PLATFORM_LONG_LABELS[account.platform]}</dd></div>
          <div><dt>Режим доступа</dt><dd>{account.accessMode}</dd></div>
          <div><dt>Внешний ID</dt><dd>{account.canonicalExternalId}</dd></div>
          <div><dt>Последний замер</dt><dd>{formatDate(account.latestObservedAt)}</dd></div>
          <div><dt>Ревизия</dt><dd>#{account.datasetRevision}</dd></div>
          <div><dt>Актуальность</dt><dd>{formatDate(account.asOf)}</dd></div>
        </dl>
      </section>
      <InfoNotice>
        Карточка использует account-level проекцию. Список публикаций не подменяется
        агрегатами: он появится после отдельного bounded endpoint.
      </InfoNotice>
      <div className="page-actions">
        {externalUrl ? <a className="button-link" href={externalUrl} target="_blank" rel="noopener noreferrer">Открыть на площадке</a> : null}
        <Link className="button-link secondary-button" href={`/institutions/${account.institutionLegacyId}?platform=${account.platform}`}>
          Карточка вуза
        </Link>
      </div>
    </>
  );
}
