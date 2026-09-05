import Link from "next/link";
import { DataProvenance, InfoNotice, Metric, PageHeader, StatusPill } from "./ui";
import { formatDate, PLATFORM_LONG_LABELS, qualityLabel } from "@/lib/format";
import type { PublicationView } from "@/lib/types";

export function PublicationDetail({
  publication,
  historyLimit,
}: {
  publication: PublicationView;
  historyLimit?: number;
}) {
  const deleted = Boolean(publication.deletedAt);
  return (
    <>
      <nav className="breadcrumbs" aria-label="Хлебные крошки">
        <Link href="/">Обзор</Link><span aria-hidden="true">/</span><span>Публикация №{publication.legacyId}</span>
      </nav>
      <PageHeader
        eyebrow={`${PLATFORM_LONG_LABELS[publication.platform]} · ${publication.publicationType}`}
        title={`Публикация №${publication.legacyId}`}
        description={`Опубликована ${formatDate(publication.publishedAt)}`}
        meta={<StatusPill tone={deleted ? "red" : "green"}>{deleted ? "удалена" : "доступна"}</StatusPill>}
      />
      {publication.intervalUncertain ? (
        <InfoNotice tone="amber">Интервал между измерениями превышает ожидаемый; дельты следует интерпретировать осторожно.</InfoNotice>
      ) : null}
      {publication.synthetic ? (
        <InfoNotice tone="amber">Последняя доступная точка помечена как synthetic baseline, а не как прямое наблюдение.</InfoNotice>
      ) : null}
      <section className="panel detail-panel">
        <div className="section-head"><div><p className="eyebrow">Последний замер</p><h2>Счётчики публикации</h2></div><StatusPill tone="blue">{publication.legacyType}</StatusPill></div>
        <div className="metrics-grid publication-metrics">
          <Metric label="реакции" value={publication.reactions.value} hint={qualityLabel(publication.reactions.quality)} />
          <Metric label="просмотры" value={publication.views.value} hint={qualityLabel(publication.views.quality)} />
          <Metric label="комментарии" value={publication.comments.value} hint={qualityLabel(publication.comments.quality)} />
          <Metric label="репосты" value={publication.shares.value} hint={qualityLabel(publication.shares.quality)} />
        </div>
        <DataProvenance
          quality={publication.quality}
          sampleSize={1}
          coverage={publication.historyCompleteness === "complete" ? 1 : null}
          asOf={publication.asOf}
          revision={publication.datasetRevision}
        />
      </section>
      <section className="panel section">
        <div className="section-head"><div><p className="eyebrow">История</p><h2>Динамика показателей</h2></div>{historyLimit ? <StatusPill tone="neutral">лимит {historyLimit}</StatusPill> : null}</div>
        <div className="embedded-empty">
          <p>Публичный Spring API сейчас отдаёт только последний согласованный замер.</p>
          <p className="muted">Параметр истории сохранён в URL-контракте, но ряд не выдумывается без bounded time-series endpoint.</p>
        </div>
      </section>
    </>
  );
}
