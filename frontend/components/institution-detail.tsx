import Link from "next/link";
import { AggregateMetrics, DataProvenance, InfoNotice, PageHeader, StatusPill } from "./ui";
import { PERIOD_LABELS, PLATFORM_LONG_LABELS } from "@/lib/format";
import { queryHref } from "@/lib/params";
import type { InstitutionView } from "@/lib/types";

export function InstitutionDetail({
  institution,
  channelCompatibility = false,
}: {
  institution: InstitutionView;
  channelCompatibility?: boolean;
}) {
  const name = institution.shortName || institution.canonicalName;
  return (
    <>
      <nav className="breadcrumbs" aria-label="Хлебные крошки">
        <Link href="/">Обзор</Link><span aria-hidden="true">/</span><span>{name}</span>
      </nav>
      <PageHeader
        eyebrow={channelCompatibility ? "Совместимый маршрут Telegram" : "Карточка вуза"}
        title={name}
        description={`${institution.canonicalName} · ${PLATFORM_LONG_LABELS[institution.platform]} · ${PERIOD_LABELS[institution.period]}`}
        meta={<StatusPill tone="blue">ID {institution.legacyId}</StatusPill>}
      />
      {channelCompatibility ? (
        <InfoNotice>
          Маршрут `/channels/{institution.legacyId}` сохранён. Текущий API публикует агрегат по вузу,
          поэтому здесь показана Telegram-проекция без выдуманного списка аккаунтов или публикаций.
        </InfoNotice>
      ) : null}
      <section className="panel detail-panel">
        <div className="section-head">
          <div><p className="eyebrow">Активность</p><h2>Показатели за период</h2></div>
          <StatusPill tone="green">данные API</StatusPill>
        </div>
        <AggregateMetrics metrics={institution.metrics} />
        <DataProvenance
          quality={institution.metrics.quality}
          sampleSize={institution.metrics.sampleSize}
          coverage={institution.metrics.coverage}
          asOf={institution.asOf}
          revision={institution.datasetRevision}
        />
      </section>
      <section className="panel section">
        <div className="section-head"><div><p className="eyebrow">Детализация</p><h2>Аккаунты и публикации</h2></div></div>
        <div className="embedded-empty">
          <p>Spring API пока не отдаёт account/publication list для этой карточки.</p>
          <p className="muted">Раздел появится после отдельного bounded endpoint; прямого чтения БД во frontend нет.</p>
        </div>
      </section>
      <div className="page-actions">
        <Link className="button-link" href={queryHref("/compare", {
          submitted: "true",
          institutions: institution.legacyId,
          platform: institution.platform,
        })}>Добавить к сравнению</Link>
        <Link className="button-link secondary-button" href={queryHref("/", {
          platform: institution.platform,
          period: institution.period,
        })}>Вернуться к обзору</Link>
      </div>
    </>
  );
}
