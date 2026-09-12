import { PlatformPending } from "@/components/platform-pending";
import type { Metadata } from "next";
import { ComparisonSelector } from "@/components/comparison-selector";
import { ComparisonVisibility } from "@/components/comparison-visibility";
import { ComparisonChart } from "@/components/comparison-chart";
import { ApiFailureState, EmptyState, InfoNotice, PageHeader } from "@/components/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
    <PageHeader
      title={platform === "telegram" ? "Сравнение каналов" : `Сравнение · ${platformLabel}`}
      description={platform === "telegram"
        ? "Сравните, как аудитория разных вузов реагирует на публикации в первые часы и дни после выхода."
        : `Сравните, как публикации вузов набирают лайки и вовлечённость в ${platformLabel} после выхода.`}
    />

    <Card className="mb-5">
      <CardContent>
        <form action="/compare" method="get" aria-label="Настройка сравнения">
          <input type="hidden" name="submitted" value="true" /><input type="hidden" name="platform" value={platform} />
          {requestedMetric ? <input type="hidden" name="metric" value={metric} /> : null}
          {requestedAggregation ? <input type="hidden" name="aggregation" value={aggregation} /> : null}
          <ComparisonSelector key={retryHref} candidates={candidates} selected={acceptedIds} type={requestedSelection.type} query={query} platformLabel={platformLabel}>
            <div className="flex flex-wrap items-end gap-x-5 gap-y-3 pt-1">
              <label className="grid gap-1.5 text-sm">
                <span className="text-muted-foreground font-medium">Период после публикации</span>
                {/* Native select: the form submits by GET and the browser
                    restores this control on back and forward navigation. */}
                <select
                  name="period"
                  defaultValue={hours}
                  className="border-input bg-transparent dark:bg-input/30 h-9 rounded-md border px-3 py-1 text-sm shadow-xs focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none"
                >
                  <option value="24">24 часа</option><option value="48">48 часов</option><option value="72">72 часа</option><option value="168">7 дней</option><option value="336">14 дней</option>
                </select>
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input name="include_partial" value="true" type="checkbox" defaultChecked={includePartial} className="accent-primary size-4" />
                Включить публикации с неполной историей
              </label>
              <Button type="submit" className="ml-auto">Показать сравнение</Button>
            </div>
          </ComparisonSelector>
        </form>
      </CardContent>
    </Card>

    <section className="mb-5 grid gap-3 md:grid-cols-2" aria-label="Как читать сравнение">
      <Card className="bg-muted/40 shadow-none">
        <CardContent className="text-muted-foreground text-sm">
          <b className="text-foreground mb-1 block font-semibold">{primaryHeading}</b>
          {platform === "telegram" ? "Одна линия — один канал и одна неизменная выборка публикаций на всём горизонте. Точка показывает медианное число реакций на соответствующем целом часу." : `Одна линия — один вуз и одна неизменная выборка публикаций ${platformLabel} на всём горизонте. Точка — медианное число ${primaryWord} на соответствующем целом часу.`}
        </CardContent>
      </Card>
      <Card className="bg-muted/40 shadow-none">
        <CardContent className="text-muted-foreground text-sm">
          <b className="text-foreground mb-1 block font-semibold">{engagementHeading}</b>
          {platform === "telegram" ? "Для каждого поста рассчитывается отношение реакций к просмотрам, затем для каждого часа берётся медиана этих процентов по каналу. Это отношение количества реакций, а не точное число людей: один пользователь Telegram Premium может оставить несколько реакций." : `Для каждой публикации: (лайки + комментарии${platform === "vk" ? " + репосты" : ""}) / просмотры. На графике показана медиана этих процентов по неизменной выборке.`}
        </CardContent>
      </Card>
    </section>

    <InfoNotice>{platform === "telegram" ? <><b>{includePartial ? "Неполная история включена:" : "Полная история:"}</b> {includePartial ? "допускаются посты, найденные после стартового порога, если у них есть данные с первого часа до конца выбранного горизонта. Выборка внутри линии не меняется." : "учитываются публикации, замеченные не позднее чем через 6 минут после выхода и имеющие замеры на всём выбранном горизонте."}</> : <><b>Постоянная выборка:</b> публикация участвует во всех точках только при наличии истории до конца выбранного горизонта{!includePartial ? " и первого замера не позднее 6 минут после выхода" : ""}.</>}</InfoNotice>
    {omittedSelectionCount > 0 ? <InfoNotice>Не сопоставлено и пропущено legacy ID: {omittedSelectionCount}.</InfoNotice> : null}
    {selectionIssue ? <EmptyState title="Выбор не принят" description={selectionMessages[selectionIssue]} /> : comparisonRejected ? <EmptyState title="Выбранный ряд недоступен" description={comparisonRejected} /> : comparisonFailed ? <ApiFailureState retryHref={retryHref} /> : !selectedCount ? <EmptyState title="Нечего сравнивать" description={`Выберите хотя бы один ${entitySingular} и нажмите «Показать сравнение».`} /> : !selectedSeries.some((series) => series.points.some((point) => point.value !== null)) ? <EmptyState title="Недостаточно замеров" description={`Для выбранных ${entityPlural} пока недостаточно замеров ${platform === "telegram" ? "" : `${platformLabel} `}на всём горизонте. Выберите более короткий период или дождитесь накопления истории.`} /> : null}
    {!comparisonFailed && !selectionIssue && !comparisonRejected ? <ComparisonVisibility key={retryHref}>
      <Card className="mt-6">
        <CardHeader className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <CardTitle className="font-heading text-lg">{primaryHeading}</CardTitle>
            <CardDescription className="mt-2">{platform === "telegram" ? "Точка — медиана на конкретном целом часу после публикации. Нажмите на вуз в легенде, чтобы скрыть или вернуть его линию." : "Точка — медиана на конкретном целом часу. Линии можно скрывать в легенде."}</CardDescription>
          </div>
          <Badge variant="secondary" className="shrink-0 rounded-full font-semibold">Первые {periodLabel}</Badge>
        </CardHeader>
        <CardContent>
          <ComparisonChart series={selectedSeries} horizonHours={hours} maximumHour={maximumHour} label={primaryHeading} metricWord={primaryWord} axisLabel={`${platform === "telegram" ? "Реакций" : "Лайков"}, ${aggregation === "median" ? "медиана" : "сумма"}`} />
        </CardContent>
      </Card>
      <Card className="mt-5">
        <CardHeader className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <CardTitle className="font-heading text-lg">{engagementHeading}</CardTitle>
            <CardDescription className="mt-2">{platform === "telegram" ? "Точка — медиана отношений «реакции / просмотры» у отдельных постов на конкретном часу. Линии включаются и выключаются общей легендой выше." : `Медиана отношений «лайки + комментарии${platform === "vk" ? " + репосты" : ""} / просмотры» у отдельных публикаций ${platformLabel}.`}</CardDescription>
          </div>
          <Badge variant="secondary" className="shrink-0 rounded-full font-semibold">Первые {periodLabel}</Badge>
        </CardHeader>
        <CardContent>
          <ComparisonChart series={engagementSeries} horizonHours={hours} maximumHour={maximumHour} label={engagementHeading} axisLabel={`${platform === "telegram" ? "Реакции" : "Взаимодействия"} / просмотры, медиана`} valueFormat="percentage" cohortKind="engagement" showLegend={false} />
        </CardContent>
      </Card>
    </ComparisonVisibility> : null}
  </>;
}
