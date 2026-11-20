import type { Metadata } from "next";
import { CalendarDays, Equal, Eye, Heart, Hourglass, Zap } from "lucide-react";
import Link from "@/components/native-link";
import { Glyphs, WeightStrip } from "@/components/rating/formula-visual";
import { OwnTable } from "@/components/rating/own-table";
import { OwnTabs } from "@/components/rating/own-tabs";
import { RatingTabs } from "@/components/rating/rating-tabs";
import { ApiFailureState, EmptyState, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { OWN_PLATFORMS, ownStatusLine, percent, plain } from "@/lib/own-rating";
import { queryHref, type SearchParams } from "@/lib/params";
import { monthLabel, normalizeMonth } from "@/lib/rating";
import type { OwnRating, RatingForecastMonths } from "@/lib/types";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Рейтинг: наша формула",
  description: "Собственный открытый рейтинг вузов по соцсетям: Telegram, VK, MAX и Rutube поровну, без накрутки.",
};

const SEGMENTS = "bg-muted text-muted-foreground inline-flex max-w-full flex-wrap gap-0.5 rounded-lg p-[3px]";
const SEGMENT = "rounded-md px-3 py-1 text-sm font-medium whitespace-nowrap transition-colors";
const SEGMENT_ACTIVE = "bg-background text-foreground shadow-sm";

/** Открытая формула картинкой — перед таблицей; пороги — из определения формулы снимка. */
function Method({ own }: { own: OwnRating }) {
  const { formula } = own;
  return <section aria-labelledby="own-method" data-testid="own-method" className="bg-muted/40 mb-6 rounded-lg p-4 sm:p-5">
    <h2 id="own-method" className="font-heading mb-3 text-base font-semibold">Как считается</h2>
    <div className="space-y-4">
    <WeightStrip weights={formula.weights} label="Балл вуза — среднее четырёх площадок поровну" />
    <div>
      <p className="mb-2 text-sm">Балл площадки — среднее трёх частей, каждая от 0 до 100:</p>
      <Glyphs items={[
        { icon: CalendarDays, label: "Дни с публикациями", detail: `100 — от ${formula.activeDays.full.vk} дней из ${formula.activeDays.perDays}, у Rutube от ${formula.activeDays.full.rutube}` },
        { icon: Eye, label: "Просмотры поста на студента", detail: "0 и 100 — нижние и верхние 10 % вузов" },
        { icon: Heart, label: "Реакции на просмотр", detail: "с комментариями и репостами" },
      ]} />
    </div>
    <div>
      <p className="mb-2 text-sm">Не засчитываем:</p>
      <Glyphs tone="minus" items={[
        { icon: Zap, label: "Пакеты реакций и просмотров" },
        { icon: Hourglass, label: "Поздние реакции сверх нормы площадки" },
        { icon: Equal, label: "Ровный отклик с долгим хвостом", detail: "вовлечённость — не выше медианы" },
      ]} />
    </div>
    <details className="text-sm">
      <summary className="cursor-pointer">Пороги и правила</summary>
      <table className="mt-2 text-xs tabular-nums" data-testid="own-thresholds">
        <thead><tr className="text-muted-foreground text-left"><th className="pr-4 font-normal">Площадка</th>
          <th className="pr-4 font-normal">Просмотров на студента</th><th className="font-normal">Реакций на просмотр</th></tr></thead>
        <tbody>{OWN_PLATFORMS.map(({ key, label }) => <tr key={key}>
          <td className="pr-4">{label}</td>
          <td className="pr-4">{plain(formula.reachPerStudent[key].low)} → {plain(formula.reachPerStudent[key].high)}</td>
          <td>{percent(formula.erv[key].low)} → {percent(formula.erv[key].high)}</td>
        </tr>)}</tbody>
      </table>
      <p className="text-muted-foreground mt-2 text-xs">Шкала логарифмическая. Нет аккаунта или публикаций за месяц — 0.
        Меньше {formula.minPosts.vk} постов ({formula.minPosts.rutube} видео) — охват и реакции пропорционально меньше.
        «*» — площадку собирали не весь месяц. Признаки статистические, а не доказательство нарушений.
        Версия {formula.version}, <Link href="/methodology/rating-forecast" className="underline">методика</Link>.</p>
    </details>
    </div>
  </section>;
}

export default async function OwnFormulaPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const month = normalizeMonth((await searchParams).month);
  let months: RatingForecastMonths;
  let own: OwnRating | null = null;
  try {
    months = await api.ownRatingMonths();
    if (months.months.length) own = await api.ownRating(month ?? undefined);
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 404)) return <ApiFailureState retryHref="/rating/own/formula" />;
    months = { months: [] };
  }
  return <>
    <PageHeader title="Рейтинг" description="Собственный вариант расчёта по нашим данным отслеживания." />
    <RatingTabs active="/rating/own" />
    <OwnTabs active="/rating/own/formula" />
    {!own ? <EmptyState title="Снимков нашего рейтинга ещё нет" description="Рейтинг считается раз в сутки ночью вместе с прогнозом М-Рейтинга, начиная с ноября 2026." /> : <>
      <Method own={own} />
      <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <nav aria-label="Месяц" className={SEGMENTS}>
          {months.months.map((item) => <Link key={item.month} href={queryHref("/rating/own/formula", { month: item.month })} prefetch={false}
            aria-current={item.month === own.month ? "page" : undefined}
            className={cn(SEGMENT, item.month === own.month ? SEGMENT_ACTIVE : "hover:text-foreground")}>
            {monthLabel(item.month)}</Link>)}
        </nav>
      </div>
      <p data-testid="own-status" className="mb-4 text-sm"><span className="font-medium">{ownStatusLine(own)}.</span>{" "}
        <span className="text-muted-foreground">В рейтинге {own.ranked} из {own.institutions} вузов — у кого есть данные хотя бы по трём площадкам.</span></p>
      <OwnTable own={own} />
    </>}
  </>;
}
