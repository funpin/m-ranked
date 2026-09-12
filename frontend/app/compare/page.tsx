import { PlatformPending } from "@/components/platform-pending";
import type { Metadata } from "next";
import { ComparisonSelector } from "@/components/comparison-selector";
import { ComparisonVisibility } from "@/components/comparison-visibility";
import { ComparisonChart } from "@/components/comparison-chart";
import { ApiFailureState, EmptyState, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { PLATFORM_LONG_LABELS } from "@/lib/format";
import {
  comparePeriod,
  comparisonPlatformIsPending,
  first,
  legacyBoolean,
  normalizePlatform,
  parseComparisonQuerySelection,
  queryHref,
  type SearchParams,
} from "@/lib/params";
import { MAX_COMPARISON_INSTITUTIONS, COMPARISON_PAGE_SIZE } from "@/lib/types";
import type {
  ComparisonAggregation,
  ComparisonMetric,
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
  const { hours } = comparePeriod(params.period);
  const query = (first(params.q) ?? "").trim();
  if (comparisonPlatformIsPending(platform)) return <PlatformPending platform={platform} kind="compare" />;
  const requestedSelection = parseComparisonQuerySelection(
    platform,
    params.submitted,
    params.channels,
    params.institutions,
  );
  const explicitSelection = requestedSelection.explicit;
  const selectionIssue = requestedSelection.issue;
  const includePartial = legacyBoolean(params.include_partial);
  const metricValues: ComparisonMetric[] = ["reactions", "views", "comments", "shares"];
  const aggregationValues: ComparisonAggregation[] = ["median", "sum"];
  const requestedMetric = first(params.metric) as ComparisonMetric | undefined;
  const requestedAggregation = first(params.aggregation) as ComparisonAggregation | undefined;
  const metric = metricValues.includes(requestedMetric as ComparisonMetric) ? requestedMetric! : "reactions";
  const aggregation = aggregationValues.includes(requestedAggregation as ComparisonAggregation) ? requestedAggregation! : "median";

  const retryHref = queryHref("/compare", { platform, period: hours, metric, aggregation,
    include_partial: String(includePartial), submitted: first(params.submitted),
    channels: requestedSelection.type === "channels" ? requestedSelection.ids : undefined,
    institutions: requestedSelection.type === "institutions" ? requestedSelection.ids : undefined });
  let candidates;
  let candidateRevision: number;
  try {
    const page = await api.comparisonCandidates(platform, 200);
    candidateRevision = page.datasetRevision;
    candidates = page.items.map((item) => ({
      id: item.selectionLegacyId, label: item.selectionLabel, description: item.selectionDescription ?? item.canonicalName,
    }));
  } catch {
    return <><PageHeader title="Сравнение каналов" description="Сопоставление показателей официальных соцсетей вузов." /><ApiFailureState retryHref={retryHref} /></>;
  }
  let comparison: ComparisonView | null = null;
  let comparisonFailed = false;
  let comparisonRejected: string | null = null;
  const intendedIds = explicitSelection ? requestedSelection.ids : candidates.slice(0, MAX_COMPARISON_INSTITUTIONS).map((item) => item.id);
  if (!selectionIssue && intendedIds.length) {
    try {
      const page = await api.comparison({ platform,
        horizonHours: hours, includePartial, metric, aggregation, institutionLimit: COMPARISON_PAGE_SIZE,
        ...(explicitSelection ? requestedSelection.type === "channels"
          ? { channels: requestedSelection.ids } : { institutions: requestedSelection.ids } : {}),
      });
      comparison = page;
      if (comparison.datasetRevision !== candidateRevision) {
        comparison = null;
        comparisonRejected = "Данные обновились во время загрузки. Повторите запрос";
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 400) comparisonRejected = error.message;
      else if (!(error instanceof ApiError && error.status === 404)) comparisonFailed = true;
    }
  }
  const selectedSeries = comparison?.series ?? [];
  let lastObserved=1;for(const series of selectedSeries)for(const point of series.points)if(point.value!==null)lastObserved=Math.max(lastObserved,point.hourOffset);
  const maximumHour=Math.min(hours,lastObserved+1);
  const acceptedIds = explicitSelection && comparison ? selectedSeries.map((item) => item.selectionLegacyId) : intendedIds;
  const selectedCount = acceptedIds.length;
  const omittedSelectionCount = explicitSelection && comparison ? Math.max(0, requestedSelection.ids.length - selectedSeries.length) : 0;
  const entityPlural = requestedSelection.type === "channels" ? "каналов" : "вузов";
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
  const engagementSeries = selectedSeries.map((series) => ({
    ...series,
    points: series.engagementPoints,
  }));

  const platformLabel = PLATFORM_LONG_LABELS[platform];
  const primaryWord = platform === "telegram" ? "реакций" : "лайков";
  const primaryHeading = aggregation === "median" && ["reactions", "views"].includes(metric) ? `Типичное накопление ${primaryWord}` : `${metricLabels[metric]} · ${aggregation === "median" ? "медиана" : "сумма"}`;
  const periodLabel = {24:"24 часа",48:"48 часов",72:"72 часа",168:"7 дней",336:"14 дней"}[hours];
  return <>
    <h1>{platform === "telegram" ? "Сравнение каналов" : `Сравнение · ${platformLabel}`}</h1>
    <p className="lead">{platform === "telegram" ? "Сравните, как аудитория разных вузов реагирует на публикации в первые часы и дни после выхода." : `Сравните, как публикации вузов набирают лайки и вовлечённость в ${platformLabel} после выхода.`}</p>
    <form className="panel selector-panel compare-selector" action="/compare" method="get" aria-label="Настройка сравнения">
      <input type="hidden" name="submitted" value="true" /><input type="hidden" name="platform" value={platform} />
      {requestedMetric ? <input type="hidden" name="metric" value={metric} /> : null}
      {requestedAggregation ? <input type="hidden" name="aggregation" value={aggregation} /> : null}
      <ComparisonSelector key={retryHref} candidates={candidates} selected={acceptedIds} type={requestedSelection.type} query={query} platformLabel={platformLabel}>
        <div className="selector-footer">
          <label>Период после публикации<br /><select name="period" defaultValue={hours}><option value="24">24 часа</option><option value="48">48 часов</option><option value="72">72 часа</option><option value="168">7 дней</option><option value="336">14 дней</option></select></label>
          <label><input name="include_partial" value="true" type="checkbox" defaultChecked={includePartial} /> Включить публикации с неполной историей</label>
          <button type="submit">Показать сравнение</button>
        </div>
      </ComparisonSelector>
    </form>
    <section className="help-grid compare-help" aria-label="Как читать сравнение">
      <div className="explain"><b>{primaryHeading}</b>{platform === "telegram" ? "Одна линия — один канал и одна неизменная выборка публикаций на всём горизонте. Точка показывает медианное число реакций на соответствующем целом часу." : `Одна линия — один вуз и одна неизменная выборка публикаций ${platformLabel} на всём горизонте. Точка — медианное число ${primaryWord} на соответствующем целом часу.`}</div>
      <div className="explain"><b>{engagementHeading}</b>{platform === "telegram" ? "Для каждого поста рассчитывается отношение реакций к просмотрам, затем для каждого часа берётся медиана этих процентов по каналу. Это отношение количества реакций, а не точное число людей: один пользователь Telegram Premium может оставить несколько реакций." : `Для каждой публикации: (лайки + комментарии${platform === "vk" ? " + репосты" : ""}) / просмотры. На графике показана медиана этих процентов по неизменной выборке.`}</div>
    </section>
    <p className="notice">{platform === "telegram" ? <><b>{includePartial ? "Неполная история включена:" : "Полная история:"}</b> {includePartial ? "допускаются посты, найденные после стартового порога, если у них есть данные с первого часа до конца выбранного горизонта. Выборка внутри линии не меняется." : "учитываются публикации, замеченные не позднее чем через 6 минут после выхода и имеющие замеры на всём выбранном горизонте."}</> : <><b>Постоянная выборка:</b> публикация участвует во всех точках только при наличии истории до конца выбранного горизонта{!includePartial ? " и первого замера не позднее 6 минут после выхода" : ""}.</>}</p>
    {omittedSelectionCount > 0 ? <p className="notice">Не сопоставлено и пропущено legacy ID: {omittedSelectionCount}.</p> : null}
    {selectionIssue ? <EmptyState title="Выбор не принят" description={selectionMessages[selectionIssue]} /> : comparisonRejected ? <EmptyState title="Выбранный ряд недоступен" description={comparisonRejected} /> : comparisonFailed ? <ApiFailureState retryHref={retryHref} /> : !selectedCount ? <div className="panel empty-state mt"><span className="sr-only">Нечего сравнивать. </span>Выберите хотя бы один {entitySingular} и нажмите «Показать сравнение».</div> : !selectedSeries.some((series) => series.points.some((point) => point.value !== null)) ? <div className="panel empty-state mt">Для выбранных {entityPlural} пока недостаточно замеров {platform === "telegram" ? "" : `${platformLabel} `}на всём горизонте. Выберите более короткий период или дождитесь накопления истории.</div> : null}
    {!comparisonFailed && !selectionIssue && !comparisonRejected ? <ComparisonVisibility key={retryHref}>
      <div className="section"><section className="panel comparison-panel">
        <div className="rating-panel-head"><div><h2>{primaryHeading}</h2><p className="panel-note">{platform === "telegram" ? "Точка — медиана на конкретном целом часу после публикации. Нажмите на вуз в легенде, чтобы скрыть или вернуть его линию." : "Точка — медиана на конкретном целом часу. Линии можно скрывать в легенде."}</p></div><span className="period-badge">Первые {periodLabel}</span></div>
        <ComparisonChart series={selectedSeries} horizonHours={hours} maximumHour={maximumHour} label={primaryHeading} metricWord={primaryWord} axisLabel={`${platform === "telegram" ? "Реакций" : "Лайков"}, ${aggregation === "median" ? "медиана" : "сумма"}`} />
      </section></div>
      {<section className="panel comparison-panel mt">
        <div className="rating-panel-head"><div><h2>{engagementHeading}</h2><p className="panel-note">{platform === "telegram" ? "Точка — медиана отношений «реакции / просмотры» у отдельных постов на конкретном часу. Линии включаются и выключаются общей легендой выше." : `Медиана отношений «лайки + комментарии${platform === "vk" ? " + репосты" : ""} / просмотры» у отдельных публикаций ${platformLabel}.`}</p></div><span className="period-badge">Первые {periodLabel}</span></div>
        <ComparisonChart series={engagementSeries} horizonHours={hours} maximumHour={maximumHour} label={engagementHeading} axisLabel={`${platform === "telegram" ? "Реакции" : "Взаимодействия"} / просмотры, медиана`} valueFormat="percentage" cohortKind="engagement" showLegend={false} />
      </section>}
    </ComparisonVisibility> : null}
  </>;
}
