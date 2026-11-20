import type { Metadata } from "next";
import Link from "@/components/native-link";
import { ForecastMethod } from "@/components/rating/method-block";
import { ForecastScatter } from "@/components/rating/forecast-scatter-lazy";
import { FORECAST_INK, ForecastTable } from "@/components/rating/forecast-table";
import { RatingTabs } from "@/components/rating/rating-tabs";
import { ApiFailureState, EmptyState, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { hasActual, monthLabel, normalizeCategory, normalizeMonth, normalizeView, RATING_CATEGORIES, RATING_VIEWS, scatterPoints, statusLine } from "@/lib/rating";
import { queryHref, type SearchParams } from "@/lib/params";
import type { RatingForecast, RatingForecastMonths } from "@/lib/types";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Рейтинг: прогноз М-Рейтинга",
  description: "Какое место вуз получит в официальном М-Рейтинге по соцсетям — оценка по нашим данным до публикации.",
};

const SEGMENTS = "bg-muted text-muted-foreground inline-flex max-w-full flex-wrap gap-0.5 rounded-lg p-[3px]";
const SEGMENT = "rounded-md px-3 py-1 text-sm font-medium whitespace-nowrap transition-colors";
const SEGMENT_ACTIVE = "bg-background text-foreground shadow-sm";

export default async function RatingPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const raw = await searchParams;
  const category = normalizeCategory(raw.category);
  const month = normalizeMonth(raw.month);
  const view = normalizeView(raw.view);
  // Режим «Прогноз» — значение по умолчанию и в адрес не пишется.
  const viewParam = view === "fact" ? "fact" : undefined;
  let months: RatingForecastMonths;
  let forecast: RatingForecast | null = null;
  let total = 233;
  try {
    const [summary, list] = await Promise.all([api.siteSummary(), api.ratingForecastMonths()]);
    months = list;
    total = summary.ratingInstitutions ?? total;
    if (months.months.length) forecast = await api.ratingForecast(month ?? undefined);
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 404)) return <ApiFailureState retryHref="/rating" />;
    months = { months: [] };
  }
  return <>
    <PageHeader title="Рейтинг" description="Оценка места вуза в официальном М-Рейтинге Минобрнауки по соцсетям — по нашим данным, до публикации официального списка." />
    <RatingTabs active="/rating" />
    {!forecast ? <EmptyState title="Снимков прогноза ещё нет" description="Прогноз считается раз в сутки ночью; первый снимок появится после ближайшего расчёта." /> : <>
      <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <nav aria-label="Месяц" className={SEGMENTS}>
          {months.months.map((item) => <Link key={item.month} href={queryHref("/rating", { month: item.month, category, view: viewParam })} prefetch={false}
            aria-current={item.month === forecast.month ? "page" : undefined}
            className={cn(SEGMENT, item.month === forecast.month ? SEGMENT_ACTIVE : "hover:text-foreground")}>
            {monthLabel(item.month)}</Link>)}
        </nav>
        <div className="flex flex-wrap gap-2">
          <nav aria-label="Прогноз или факт" data-testid="rating-view" className={SEGMENTS}>
            {RATING_VIEWS.map((item) => <Link key={item.value} href={queryHref("/rating", { month: forecast.month, category,
              view: item.value === "fact" ? "fact" : undefined })}
              prefetch={false} aria-current={item.value === view ? "page" : undefined}
              className={cn(SEGMENT, item.value === view ? SEGMENT_ACTIVE : "hover:text-foreground")}>
              {item.label}</Link>)}
          </nav>
          <nav aria-label="Категория" data-testid="rating-category" className={SEGMENTS}>
            {RATING_CATEGORIES.map((item) => <Link key={item.value} href={queryHref("/rating", { month: forecast.month, category: item.value, view: viewParam })}
              prefetch={false} aria-current={item.value === category ? "page" : undefined}
              className={cn(SEGMENT, item.value === category ? SEGMENT_ACTIVE : "hover:text-foreground")}>
              {item.label}</Link>)}
          </nav>
        </div>
      </div>
      <p data-testid="rating-status" className="mb-1 text-sm font-medium">{forecast.period}. {statusLine(forecast)}</p>
      <p className="text-muted-foreground mb-4 max-w-3xl text-sm">Места — среди {total} вузов официального рейтинга; под прогнозным
        местом — диапазон при типичной ошибке прогноза. <span className={cn(FORECAST_INK, "font-medium")}>Прогноз</span> — наша оценка,
        {" "}<span className="text-foreground border-foreground/40 rounded border px-1">факт</span> — официальный список.
        ± — разница прогноза и факта, Δ — сдвиг против {forecast.basePeriod.toLowerCase()}; плюс и ↑ — место выше.
        Только соцсети: СМИ, сайт и повестка Минобрнауки не прогнозируются.</p>
      {view === "fact" && !hasActual(forecast)
        ? <EmptyState title={`Официальный рейтинг за ${forecast.period.toLowerCase()} ещё не опубликован или не загружен`}
          description="Факт появится после публикации на m-rating.ru и загрузки официального списка; пока доступен прогноз." />
        : <ForecastTable forecast={forecast} category={category} view={view} total={total} />}
      {hasActual(forecast) ? <ForecastScatter points={scatterPoints(forecast.rows, category)} total={total} /> : null}
      <ForecastMethod forecast={forecast} />
    </>}
  </>;
}
