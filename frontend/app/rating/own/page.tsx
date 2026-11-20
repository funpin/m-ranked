import type { Metadata } from "next";
import Link from "@/components/native-link";
import { CleanTable, placeShift } from "@/components/rating/clean-table";
import { OwnTabs } from "@/components/rating/own-tabs";
import { RatingTabs } from "@/components/rating/rating-tabs";
import { ApiFailureState, EmptyState, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { queryHref, type SearchParams } from "@/lib/params";
import { monthLabel, normalizeMonth } from "@/lib/rating";
import type { RatingClean, RatingForecastMonths } from "@/lib/types";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Рейтинг: М-Рейтинг без накрутки",
  description: "Места вузов в М-Рейтинге по соцсетям, пересчитанные без замеренной накрутки реакций и просмотров.",
};

const SEGMENTS = "bg-muted text-muted-foreground inline-flex max-w-full flex-wrap gap-0.5 rounded-lg p-[3px]";
const SEGMENT = "rounded-md px-3 py-1 text-sm font-medium whitespace-nowrap transition-colors";
const SEGMENT_ACTIVE = "bg-background text-foreground shadow-sm";
const FILTERS = [{ value: undefined, label: "Все вузы" }, { value: "changed", label: "Только со сдвигом" }] as const;

/** Открытая формула — перед таблицей, как просил владелец: что вычитается и откуда берётся основа. */
function Method({ clean }: { clean: RatingClean }) {
  return <section aria-labelledby="clean-method" data-testid="clean-method" className="bg-muted/40 mb-5 rounded-lg p-4 text-sm">
    <h2 id="clean-method" className="font-heading mb-2 text-base font-semibold">Как считается</h2>
    <p className="mb-2">Тот же балл соцсетей, что у М-Рейтинга по нашей реконструкции формулы:{" "}
      <span className="font-medium">соцсети = 0.4 × MAX + 0.3 × VK + 0.3 × Rutube</span>; балл VK и MAX — среднее трёх частей:
      число постов за месяц, средние просмотры поста на студента и доля реакций, комментариев и репостов на просмотр.
      Из VK и MAX вычитается то, что наш анализ замерил как накрутку:</p>
    <ol className="mb-2 list-decimal space-y-1 pl-5">
      <li><span className="font-medium">Пакеты на постах с явными признаками</span> (уровень 3): реакции и просмотры, пришедшие одним
        эпизодом, — пакет реакций с остановкой, реакции раньше просмотров, рывок, обрывающийся в плато, и другие. С поста убирается
        крупнейший эпизод каждой метрики; по просмотрам — ещё волны по стене и всплески без отклика.</li>
      <li><span className="font-medium">«Умная» накрутка аккаунта</span>: посты одного дня получают почти одинаковое число реакций
        (разброс сверх случайного не выше 0.10 в MAX и 0.25 в VK) и при этом старые посты добирают реакции на просмотр активнее,
        чем у 90 % аккаунтов площадки. Убираются поздние реакции сверх обычного для площадки хвоста.</li>
    </ol>
    <p className="mb-2"><span className="font-medium">Только отмечается, не вычитается:</span> Rutube, у которого порог
      «5 видео за месяц» взят лишь благодаря пачке роликов, загруженных за один день. Это не накрутка просмотров,
      а игра с порогом — балл Rutube остаётся официальным.</p>
    <p className="mb-2">Сдвиг балла площадки — разница нашей формулы на месяце как есть и без накрутки; он вычитается
      {clean.basis === "fact" ? " из официального балла М-Рейтинга" : " из нашего прогноза — официального балла за этот месяц ещё нет"}.
      Rutube, СМИ, сайт и повестка не меняются; места — среди всех вузов рейтинга, баллы неотслеживаемых вузов прежние.</p>
    <p className="text-muted-foreground">Накрутка выгодна в М-Рейтинге в основном реакциями: доля реакций упирается в потолок
      3.5 % в VK и 8 % в MAX, а лишние просмотры её снижают, поэтому вычитание одних просмотров может даже поднять балл.
      Это статистическая оценка необычной активности, а не доказательство накрутки.</p>
  </section>;
}

export default async function CleanRatingPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const raw = await searchParams;
  const month = normalizeMonth(raw.month);
  const changed = raw.filter === "changed";
  let months: RatingForecastMonths;
  let clean: RatingClean | null = null;
  try {
    months = await api.ratingCleanMonths();
    if (months.months.length) clean = await api.ratingClean(month ?? undefined);
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 404)) return <ApiFailureState retryHref="/rating/own" />;
    months = { months: [] };
  }
  const filter = changed ? "changed" : undefined;
  const rows = clean ? clean.rows.filter((row) => row.categories.social && (!changed || placeShift(row) !== 0))
    .sort((a, b) => a.categories.social!.rank - b.categories.social!.rank) : [];
  return <>
    <PageHeader title="Рейтинг" description="Собственный вариант расчёта по нашим данным отслеживания." />
    <RatingTabs active="/rating/own" />
    <OwnTabs active="/rating/own" />
    {!clean ? <EmptyState title="Снимков без накрутки ещё нет" description="Они считаются вместе с ночным прогнозом М-Рейтинга." /> : <>
      <Method clean={clean} />
      <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <nav aria-label="Месяц" className={SEGMENTS}>
          {months.months.map((item) => <Link key={item.month} href={queryHref("/rating/own", { month: item.month, filter })} prefetch={false}
            aria-current={item.month === clean.month ? "page" : undefined}
            className={cn(SEGMENT, item.month === clean.month ? SEGMENT_ACTIVE : "hover:text-foreground")}>
            {monthLabel(item.month)}</Link>)}
        </nav>
        <nav aria-label="Какие вузы показать" data-testid="clean-filter" className={SEGMENTS}>
          {FILTERS.map((item) => <Link key={item.label} href={queryHref("/rating/own", { month: clean.month, filter: item.value })} prefetch={false}
            aria-current={item.value === filter ? "page" : undefined}
            className={cn(SEGMENT, item.value === filter ? SEGMENT_ACTIVE : "hover:text-foreground")}>
            {item.label}</Link>)}
        </nav>
      </div>
      <p data-testid="clean-status" className="text-muted-foreground mb-4 max-w-3xl text-sm">{clean.period}: основа —{" "}
        {clean.basis === "fact" ? `официальный М-Рейтинг за ${clean.basisPeriod.toLowerCase()}` : "наш прогноз, месяц ещё не опубликован"}.
        Сдвиг: ↓ — без накрутки вуз ниже, ↑ — выше, потому что обогнал опустившихся.</p>
      {rows.length ? <CleanTable clean={clean} rows={rows} />
        : <EmptyState title="Сдвигов нет" description="Ни у одного вуза за этот месяц накрутка не меняет место." />}
    </>}
  </>;
}
