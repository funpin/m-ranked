import type { Metadata } from "next";
import { ComparisonChart } from "@/components/comparison-chart";
import { ApiFailureState, EmptyState, InfoNotice, PageHeader, StatusPill } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { PLATFORM_LABELS } from "@/lib/format";
import {
  comparePeriod,
  comparisonPlatformIsPending,
  defaultComparisonSelection,
  first,
  normalizePlatform,
  parseComparisonQuerySelection,
  type SearchParams,
} from "@/lib/params";
import { MAX_COMPARISON_INSTITUTIONS, PLATFORM_VALUES } from "@/lib/types";
import type {
  ComparisonAggregation,
  ComparisonMetric,
  ComparisonSeries,
  ComparisonView,
} from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Сравнение каналов",
  description: "Сопоставление накопления метрик и вовлечённости официальных соцсетей вузов в одном срезе данных.",
  openGraph: {
    title: "Сравнение каналов — M‑Ranked",
    description: "Сопоставление накопления метрик и вовлечённости официальных соцсетей вузов в одном срезе данных.",
  },
  twitter: {
    card: "summary",
    title: "Сравнение каналов — M‑Ranked",
    description: "Сопоставление медианных реакций и просмотров официальных соцсетей вузов в одном срезе данных.",
  },
};

export default async function ComparePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const platform = normalizePlatform(params.platform, "telegram");
  const { hours, apiPeriod } = comparePeriod(params.period);
  const query = (first(params.q) ?? "").trim().slice(0, 200);
  if (comparisonPlatformIsPending(platform)) {
    return (
      <>
        <PageHeader
          title="Сравнение каналов"
          description="Сравнение использует публикации и фиксированные выборки только одной площадки."
          meta={<StatusPill tone="amber">в подготовке</StatusPill>}
        />
        <EmptyState
          title="Сравнение пока недоступно"
          description={platform === "all"
            ? "Выберите Telegram, VK или RUTUBE: объединять медианы разных площадок некорректно."
            : "Для MAX фиксированные cohort‑ряды ещё не подключены к этой странице."}
        />
      </>
    );
  }
  const requestedSelection = parseComparisonQuerySelection(
    platform,
    params.submitted,
    params.channels,
    params.institutions,
  );
  const explicitSelection = requestedSelection.explicit;
  const selectionIssue = requestedSelection.issue;
  const includePartial = first(params.include_partial) === "true";
  const metricValues: ComparisonMetric[] = ["reactions", "views", "comments", "shares"];
  const aggregationValues: ComparisonAggregation[] = ["median", "sum"];
  const requestedMetric = first(params.metric) as ComparisonMetric | undefined;
  const requestedAggregation = first(params.aggregation) as ComparisonAggregation | undefined;
  const metric = metricValues.includes(requestedMetric as ComparisonMetric) ? requestedMetric! : "reactions";
  const aggregation = aggregationValues.includes(requestedAggregation as ComparisonAggregation) ? requestedAggregation! : "median";

  let page;
  try {
    page = await api.overview({ platform, period: apiPeriod, q: query, limit: 200 });
  } catch {
    return (
      <>
        <PageHeader title="Сравнение каналов" description="Сопоставление показателей официальных соцсетей вузов." />
        <ApiFailureState retryHref="/compare" />
      </>
    );
  }

  let comparison: ComparisonView | null = null;
  let defaultComparison: ComparisonView | null = null;
  let comparisonFailed = false;
  let comparisonRejected: string | null = null;
  const comparisonRequest = {
    platform,
    horizonHours: hours,
    includePartial,
    metric,
    aggregation,
    institutionLimit: MAX_COMPARISON_INSTITUTIONS,
  };
  if (platform === "telegram") {
    try {
      defaultComparison = await api.comparison(comparisonRequest);
    } catch (error) {
      if (!explicitSelection && !(error instanceof ApiError && error.status === 404)) {
        comparisonFailed = true;
      }
    }
  }

  const hasRequestedSelection = !explicitSelection || requestedSelection.ids.length > 0;
  if (!selectionIssue && hasRequestedSelection) {
    if (!explicitSelection && defaultComparison) {
      comparison = defaultComparison;
    } else {
      try {
        comparison = await api.comparison({
          ...comparisonRequest,
          ...(requestedSelection.type === "channels"
            ? { channels: requestedSelection.ids }
            : { institutions: requestedSelection.ids }),
        });
      } catch (error) {
        if (error instanceof ApiError && error.status === 400) {
          comparisonRejected = error.message;
        } else if (!(error instanceof ApiError && error.status === 404)) {
          comparisonFailed = true;
        }
      }
    }
  }
  const defaultIds = defaultComparison?.series.map((item) => item.selectionLegacyId)
    ?? comparison?.series.map((item) => item.selectionLegacyId)
    ?? (platform === "telegram"
      ? []
      : defaultComparisonSelection(page.items.map((item) => item.legacyId)));
  const intendedIds = explicitSelection ? requestedSelection.ids : defaultIds;
  const selectedSeries = comparison?.series ?? [];
  const acceptedIds = comparison
    ? selectedSeries.map((item) => item.selectionLegacyId)
    : intendedIds;
  const selectedIds = new Set(acceptedIds);
  const selectedCount = acceptedIds.length;
  const omittedSelectionCount = explicitSelection && comparison
    ? Math.max(0, requestedSelection.ids.length - selectedSeries.length)
    : 0;
  const queryKey = query.toLocaleLowerCase("ru");
  const comparisonSeriesById = new Map<number, ComparisonSeries>();
  for (const series of [...(defaultComparison?.series ?? []), ...selectedSeries]) {
    comparisonSeriesById.set(series.selectionLegacyId, series);
  }
  const channelCandidates = [...comparisonSeriesById.values()].filter((series) => {
    if (selectedIds.has(series.selectionLegacyId) || !queryKey) return true;
    return `${series.selectionLabel} ${series.shortName ?? ""} ${series.canonicalName}`
      .toLocaleLowerCase("ru")
      .includes(queryKey);
  });
  const institutionCandidates = page.items;
  const entityPlural = requestedSelection.type === "channels" ? "каналов" : "вузов";
  const entitySelection = requestedSelection.type === "channels" ? "каналы" : "вузы";
  const entitySingular = requestedSelection.type === "channels" ? "канал" : "вуз";
  const selectionMessages = {
    too_many: `Выбрано больше ${MAX_COMPARISON_INSTITUTIONS} ${entityPlural}. Снимите лишние флажки и повторите запрос.`,
    invalid: `В URL есть некорректный ID ${entitySingular === "канал" ? "канала" : "вуза"}. Допустимы только положительные целые числа.`,
  } as const;
  const metricLabels: Record<ComparisonMetric, string> = {
    reactions: "Реакции",
    views: "Просмотры",
    comments: "Комментарии",
    shares: "Репосты",
  };
  const engagementHeading = platform === "telegram"
    ? "Конверсия просмотров в реакции"
    : "Вовлечённость от просмотров";
  const engagementFormula = platform === "telegram"
    ? "реакции / просмотры"
    : platform === "vk"
      ? "лайки + комментарии + репосты / просмотры"
      : "лайки + комментарии / просмотры";
  const engagementSeries = selectedSeries.map((series) => ({
    ...series,
    points: series.engagementPoints,
  }));

  return (
    <>
      <PageHeader
        title="Сравнение каналов"
        description="Сравните реакцию аудитории вузов по одному согласованному срезу данных."
        meta={selectionIssue
          ? <StatusPill tone="amber">выбор не принят</StatusPill>
          : <StatusPill tone="blue">выбрано {selectedCount}</StatusPill>}
      />

      <form className="panel compare-selector" action="/compare" method="get" aria-label="Настройка сравнения">
        <input type="hidden" name="submitted" value="true" />
        <div className="section-head"><div><p className="eyebrow">Настройка</p><h2>Выберите {entitySelection}</h2></div><StatusPill tone="neutral">не более {MAX_COMPARISON_INSTITUTIONS}</StatusPill></div>
        <div className="selector-toolbar">
          <label className="field"><span>Поиск {entitySingular === "канал" ? "канала" : "вуза"}</span><input name="q" type="search" defaultValue={query} maxLength={200} placeholder="Название или сокращение" /></label>
          <span className="selection-summary muted">На одном графике — до {MAX_COMPARISON_INSTITUTIONS} рядов</span>
        </div>
        <div className="choice-grid">
          {requestedSelection.type === "channels"
            ? channelCandidates.map((item) => (
              <label className="choice" key={item.selectionId}>
                <input
                  type="checkbox"
                  name="channels"
                  value={item.selectionLegacyId}
                  defaultChecked={selectedIds.has(item.selectionLegacyId)}
                />
                <span className="choice-copy"><strong>{item.selectionLabel}</strong><small>{item.shortName || item.canonicalName} · ID {item.selectionLegacyId}</small></span>
              </label>
            ))
            : institutionCandidates.map((item) => (
              <label className="choice" key={item.institutionId}>
                <input
                  type="checkbox"
                  name="institutions"
                  value={item.legacyId}
                  defaultChecked={selectedIds.has(item.legacyId)}
                />
                <span className="choice-copy"><strong>{item.shortName || item.canonicalName}</strong><small>{item.canonicalName} · ID {item.legacyId}</small></span>
              </label>
            ))}
        </div>
        <div className="selector-footer">
          <label className="field"><span>Период после публикации</span><select name="period" defaultValue={hours}>
            <option value="24">24 часа</option><option value="48">48 часов</option><option value="72">72 часа</option><option value="168">7 дней</option><option value="336">14 дней</option>
          </select></label>
          <label className="field"><span>Площадка</span><select name="platform" defaultValue={platform}>
            {PLATFORM_VALUES.map((value) => <option value={value} key={value}>{PLATFORM_LABELS[value]}</option>)}
          </select></label>
          <label className="field"><span>Метрика</span><select name="metric" defaultValue={metric}>
            {metricValues.map((value) => <option value={value} key={value}>{metricLabels[value]}</option>)}
          </select></label>
          <label className="field"><span>Агрегация</span><select name="aggregation" defaultValue={aggregation}>
            <option value="median">Медиана</option><option value="sum">Сумма</option>
          </select></label>
          <label className="checkbox-line"><input name="include_partial" value="true" type="checkbox" defaultChecked={includePartial} />Неполная история</label>
          <button type="submit">Показать сравнение</button>
        </div>
      </form>

      <InfoNotice>
        Кривые читаются из фиксированной cohort‑проекции для горизонта {hours} ч; состав выборки не меняется между точками.
        Поиск кандидатов использует bounded‑срез «{apiPeriod}», а не raw snapshots.
        Companion‑кривая сначала считает процент для каждой публикации, затем берёт медиану;
        это не отношение агрегированных медиан. Primary и companion используют отдельные
        неизменные подвыборки с валидными границами.
        {omittedSelectionCount > 0
          ? ` Не сопоставлено и пропущено legacy ID: ${omittedSelectionCount}; замена другими рядами не выполнялась.`
          : null}
      </InfoNotice>

      {selectionIssue ? (
        <EmptyState
          title="Выбор не принят"
          description={selectionMessages[selectionIssue]}
        />
      ) : comparisonRejected ? (
        <EmptyState
          title="Выбранный ряд недоступен"
          description={`${comparisonRejected}. Измените выбор: API не подменяет отсутствующие ряды другими вузами.`}
        />
      ) : !selectedCount ? (
        <EmptyState
          title="Нечего сравнивать"
          description={omittedSelectionCount > 0
            ? "Указанные legacy ID не соответствуют включённым кандидатам этой площадки."
            : `Выберите хотя бы один ${entitySingular} и примените настройки.`}
        />
      ) : comparisonFailed ? (
        <ApiFailureState retryHref="/compare" />
      ) : selectedSeries.length && comparison ? (
        <>
          <section className="panel section">
            <div className="section-head">
              <div><p className="eyebrow">Фиксированная выборка · {aggregation === "median" ? "медиана" : "сумма"}</p><h2>{metricLabels[metric]} по часам</h2></div>
              <StatusPill tone="green">ревизия #{comparison.datasetRevision}</StatusPill>
            </div>
            <ComparisonChart series={selectedSeries} horizonHours={comparison.horizonHours} label={`${metricLabels[metric]} по часам`} />
            <p className="muted chart-footnote">Cohort {comparison.cohortId} · базовая выборка {comparison.cohortSampleSize} публикаций · {comparison.includePartial ? "включена неполная история" : "только полные ряды"}</p>
          </section>
          <section className="panel section">
            <div className="section-head">
              <div>
                <p className="eyebrow">Медиана отношений по отдельным публикациям</p>
                <h2>{engagementHeading}</h2>
              </div>
              <StatusPill tone="neutral">проценты</StatusPill>
            </div>
            <p className="muted">
              Точка — медиана отношений «{engagementFormula}» на конкретном целом часу.
              Доступная более ранняя точка переносится вперёд; будущие наблюдения и интерполяция не используются.
            </p>
            <ComparisonChart
              series={engagementSeries}
              horizonHours={comparison.horizonHours}
              label={engagementHeading}
              valueFormat="percentage"
              cohortKind="engagement"
            />
            <p className="muted chart-footnote">
              Для companion‑кривой состав публикаций фиксируется отдельно по валидному отношению на старте и в конце горизонта.
              {platform === "telegram" ? " Первая точка — через 1 час после публикации." : null}
            </p>
          </section>
        </>
      ) : (
        <EmptyState title="Кривая пока не рассчитана" description="Для выбранной площадки, горизонта и режима полноты нет готовой cohort‑проекции." />
      )}
    </>
  );
}
