import type { Metadata } from "next";
import { Equal, Waves, Zap } from "lucide-react";
import Link from "@/components/native-link";
import { PlatformLogo } from "@/components/platform-logo";
import { Glyphs, GroupLabel, WeightStrip } from "@/components/rating/formula-visual";
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

/** Открытая формула картинкой — перед таблицей: основа и что из неё вычитается. */
function Method({ clean }: { clean: RatingClean }) {
  return <section aria-labelledby="clean-method" data-testid="clean-method" className="bg-muted/40 mb-6 rounded-lg p-4 sm:p-5">
    <h2 id="clean-method" className="font-heading mb-3 text-base font-semibold">Как считается</h2>
    <div className="space-y-4">
    <WeightStrip weights={{ max: 0.4, vk: 0.3, rutube: 0.3 }} label="Тот же балл соцсетей, что у М-Рейтинга" />
    <div>
      <GroupLabel>Тот же балл, что у М-Рейтинга, но из VK и MAX вычитаем</GroupLabel>
      <Glyphs tone="minus" items={[
        { icon: Zap, label: "Пакеты реакций и просмотров", detail: "крупнейший эпизод на посте с явными признаками" },
        { icon: Equal, label: "Ровный отклик с долгим хвостом", detail: "поздние реакции сверх нормы площадки" },
        { icon: Waves, label: "Волны просмотров по стене", detail: "и всплески без отклика" },
      ]} />
    </div>
    <p className="text-muted-foreground flex items-center gap-2 text-xs">
      <PlatformLogo platform="rutube" size={14} decorative />Rutube, взявший порог «5 видео» пачкой роликов за один день, только отмечаем — балл не меняется</p>
    <p className="text-muted-foreground text-xs">Сдвиг вычитается {clean.basis === "fact" ? "из официального балла" : "из нашего прогноза: официального балла ещё нет"};
      Rutube, СМИ, сайт и повестка не меняются. Признаки статистические, а не доказательство накрутки.</p>
    </div>
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
      <p data-testid="clean-status" className="text-muted-foreground mb-4 text-sm">Основа —{" "}
        {clean.basis === "fact" ? `официальный М-Рейтинг за ${clean.basisPeriod.toLowerCase()}` : "наш прогноз"}.
        <span className="text-success"> ↑</span><span className="text-destructive">↓</span> — место без накрутки против основы.</p>
      {rows.length ? <CleanTable clean={clean} rows={rows} />
        : <EmptyState title="Сдвигов нет" description="Ни у одного вуза за этот месяц накрутка не меняет место." />}
    </>}
  </>;
}
