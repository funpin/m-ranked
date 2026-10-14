"use client";

import { use } from "react";
import {
  ArrowUpFromLine, ChevronRight, CircleCheck, Eye, History, Layers, Megaphone, Moon, Package, ScanLine, Timer, TrendingUp, TriangleAlert, Waves,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { StatusPill } from "@/components/ui";
import { MethodNote } from "@/components/method-note";
import { tailSummary, type TailProfileLoad } from "@/lib/account-tail";
import { PLATFORM_LABELS } from "@/lib/format";
import type { AccountAnomalyFinding, AccountAnomalyFindings } from "@/lib/types";
import { cn } from "@/lib/utils";
import { figureComparison as comparison } from "@/lib/finding-figure";
import { ReactionCorridor } from "@/components/reaction-corridor";
import { CompareBars, ColumnChart, DailyShareChart, StatTiles, WaveCalendar, shortDay, type BarItem } from "@/components/finding-charts";

export type FindingsLoad = AccountAnomalyFindings | null;

const METHOD = "Закономерности, которые видны только на многих постах сразу. Аккаунт сравнивается с другими "
  + "аккаунтами своей площадки за 30 дней; полосы показывают его значение рядом с типичным для площадки. «Устойчиво» — "
  + "и в первой, и во второй половине окна. Находки считаются отдельно и не меняют уровни постов; посты, из "
  + "которых складывается находка, ссылаются на неё. Необычное бывает и у живой аудитории: находка сама по "
  + "себе не доказывает искусственное происхождение активности или действия университета.";

// Строк находок в карточке целиком; остальные свёрнуты одной строкой.
const VISIBLE_ROWS = 3;

const ICONS: Record<string, LucideIcon> = {
  early_pack: Package, regular_reactions: ScanLine, late_growth: TrendingUp, late_engagement: History,
  synchronous_waves: Layers, engagement_shift: ArrowUpFromLine, night_reactions: Moon,
  view_packs: Eye, view_waves: Waves, level3_share: TriangleAlert, promotion: Megaphone, early_response: Timer,
};

type Figure = NonNullable<AccountAnomalyFinding["figure"]>;

/** Строка блока: находка или профиль отклика на старые посты, если находкой он не стал. */
type Row = {
  key: string; title: string; status: string | null; strong: boolean; finding: boolean; notable: boolean;
  headline: string; details: React.ReactNode;
  /** График в строке карточки: короткий, без осей. */
  inline: React.ReactNode;
  /** График в «подробнее»: с подписанными осями, свой для каждого вида находки. */
  chart: React.ReactNode;
};

/** Карточка ленты: находки сразу видны строками с графиком «этот аккаунт ↔
 *  типичный», а длинное объяснение каждой открывается отдельным окном. */
export function AccountAnalysisCard({ findings, tail, platform }: {
  findings: Promise<FindingsLoad> | null; tail: Promise<TailProfileLoad> | null; platform: string;
}) {
  const loadedFindings = findings ? use(findings) : null;
  const loadedTail = tail ? use(tail) : null;
  const rows = buildRows(loadedFindings, loadedTail, platform);
  const found = rows.filter((row) => row.finding);
  const notable = rows.filter((row) => !row.finding && row.notable);
  return (
    <section className="bg-card flex h-full min-w-0 flex-col rounded-xl border p-4 text-sm" id="account-findings"
      aria-labelledby="account-analysis-title" data-testid="account-analysis-card">
      <div className="mb-1 flex items-start gap-2">
        <div className="min-w-0 flex-1" data-testid="account-analysis-summary">
          <h2 id="account-analysis-title" className="font-heading text-sm font-semibold">Анализ аккаунта</h2>
          <p className="text-muted-foreground mt-0.5 text-xs">
            {found.length ? <>{found.length} {plural(found.length)} за 30 дней</>
              : notable.length ? notable.map((row) => `${row.title}: ${row.status}`).join(" · ")
                : rows.length ? "Находок нет: аккаунт ведёт себя как типичный для площадки" : "Данных для анализа пока мало"}
          </p>
        </div>
        {found.length ? <StatusPill tone="amber">{found.length} {plural(found.length)}</StatusPill> : null}
        <MethodNote title="Анализ аккаунта">{METHOD}</MethodNote>
      </div>
      {rows.length ? (<>
        <ul className="divide-border -mx-1 mt-2 divide-y">
          {rows.slice(0, VISIBLE_ROWS).map((row) => <AnalysisRow key={row.key} row={row} />)}
        </ul>
        {rows.length > VISIBLE_ROWS ? (
          // У «особо отличившихся» аккаунтов (МИРЭА, СКФУ) пять-шесть находок:
          // полностью — первые три, остальные одной строкой, график — в «подробнее».
          <details className="group -mx-1 border-t" data-testid="account-findings-more">
            <summary className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 flex cursor-pointer list-none items-center gap-1 rounded-md px-1 py-2 text-xs focus-visible:ring-[3px] focus-visible:outline-none [&::-webkit-details-marker]:hidden">
              <ChevronRight className="size-3 transition-transform group-open:rotate-90" aria-hidden="true" />
              <span className="group-open:hidden">Ещё {rows.length - VISIBLE_ROWS}: {rows.slice(VISIBLE_ROWS).map((row) => row.title).join(", ")}</span>
              <span className="hidden group-open:inline">Свернуть</span>
            </summary>
            <ul className="divide-border divide-y">
              {rows.slice(VISIBLE_ROWS).map((row) => <AnalysisRow key={row.key} row={row} compact />)}
            </ul>
          </details>
        ) : null}
      </>) : (
        <p className="text-muted-foreground mt-auto flex items-center gap-1.5 py-6 text-xs">
          <CircleCheck className="size-4" aria-hidden="true" />Признаков, общих для многих постов, не найдено.
        </p>
      )}
    </section>
  );
}

function AnalysisRow({ row, compact = false }: { row: Row; compact?: boolean }) {
  const Icon = ICONS[row.key] ?? History;
  return (
    <li data-testid="account-finding" data-kind={row.key} className="grid min-w-0 gap-2 px-1 py-3">
      <div className="flex min-w-0 items-start gap-2">
        <Icon className={cn("mt-0.5 size-4 shrink-0", row.finding ? "text-chart-3" : "text-muted-foreground")} aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-semibold">{row.title}</span>
            {row.status ? <StatusPill tone={row.strong ? "amber" : "neutral"}>{row.status}</StatusPill> : null}
          </div>
          <p className={cn("text-muted-foreground mt-0.5 text-xs leading-relaxed", compact && "line-clamp-1")} title={compact ? row.headline : undefined}>{row.headline}</p>
        </div>
        {row.details ? (
          <Dialog>
            <DialogTrigger className="text-foreground/80 hover:bg-muted hover:text-foreground focus-visible:ring-ring/50 inline-flex shrink-0 items-center gap-0.5 rounded-md px-2 py-1 text-xs focus-visible:ring-[3px] focus-visible:outline-none">
              подробнее<ChevronRight className="size-3" aria-hidden="true" />
            </DialogTrigger>
            <DialogContent className="max-w-xl" data-testid="account-finding-details">
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2"><Icon className="text-chart-3 size-4" aria-hidden="true" />{row.title}</DialogTitle>
                <DialogDescription>{row.headline}</DialogDescription>
              </DialogHeader>
              {row.chart ? <div className="grid gap-4">{row.chart}</div> : null}
              <div className="grid gap-3 text-xs leading-relaxed">{row.details}</div>
            </DialogContent>
          </Dialog>
        ) : null}
      </div>
      {row.inline && !compact ? <div className="pl-6">{row.inline}</div> : null}
    </li>
  );
}

function buildRows(findings: FindingsLoad, tail: TailProfileLoad, platform: string): Row[] {
  const rows: Row[] = (findings?.items ?? []).map((item) => {
    const visual = findingVisuals(item, platform);
    return {
      key: item.kind, title: item.title ?? item.kind, status: item.statusLabel, strong: item.status === 2, finding: true, notable: true,
      headline: item.headline ?? item.summary ?? "", inline: visual.inline, chart: visual.chart,
      details: <>
        {item.summary ? <p>{item.summary}.</p> : null}
        {item.kind === "late_engagement" && tail ? <TailDetails tail={tail} /> : null}
        <p className="text-muted-foreground">
          {item.membersCount ? `Постов в находке: ${item.membersCount} — они отмечены на своих страницах. ` : null}
          {item.alternatives ? `Другие объяснения: ${lower(item.alternatives)}.` : null}
        </p>
      </>,
    };
  });
  // Профиль отклика на старые посты — отдельной строкой, только если находкой он не стал.
  if (tail?.metrics && !rows.some((row) => row.key === "late_engagement")) {
    const view = tailSummary(tail);
    const cohort = tail.metrics.cohort;
    const figure: Figure | null = tail.metrics.ratio !== null && cohort?.median != null
      ? { value: tail.metrics.ratio, typical: cohort.median, unit: "times", label: "поздняя доля реакций к ранней", direction: "higher" }
      : null;
    const notable = (tail.level ?? 0) >= 1;
    rows.push({
      key: "late_engagement", title: "Отклик на старые посты", status: view.label, strong: false, finding: false, notable,
      headline: tail.level === 0 ? "Как у большинства аккаунтов площадки"
        : cohort?.rank !== undefined ? `Выше, чем у ${Math.round(cohort.rank * 100)} % аккаунтов площадки`
          : view.abstainText ?? view.label,
      inline: figure ? <FigureBars figure={figure} platform={platform} accent={notable} showGap={notable} /> : null,
      chart: figure ? <FigureBars figure={figure} platform={platform} accent={notable} showGap={notable} axis /> : null,
      details: <TailDetails tail={tail} />,
    });
  }
  return rows;
}

/** Графики находки по её виду: короткий — в строку карточки, подробный — в окно. */
function findingVisuals(item: AccountAnomalyFinding, platform: string): { inline: React.ReactNode; chart: React.ReactNode } {
  const metrics = (item.metrics ?? {}) as Record<string, unknown>;
  const num = (key: string) => typeof metrics[key] === "number" ? metrics[key] as number : null;
  const cohortMedian = typeof (metrics.cohort as { median?: unknown } | undefined)?.median === "number"
    ? (metrics.cohort as { median: number }).median : null;
  const figure = item.figure;
  const bars = figure ? <FigureBars figure={figure} platform={platform} kind={item.kind} accent showGap /> : null;
  const axisBars = figure ? <FigureBars figure={figure} platform={platform} kind={item.kind} accent showGap axis /> : null;
  switch (item.kind) {
    case "regular_reactions": {
      const corridor = corridorPoints(metrics);
      if (!corridor) return { inline: bars, chart: axisBars };
      return {
        inline: <ReactionCorridor points={corridor.points} dayMinPosts={corridor.dayMinPosts} compact />,
        chart: <ReactionCorridor points={corridor.points} dayMinPosts={corridor.dayMinPosts} />,
      };
    }
    case "early_pack": {
      const early = rate(num("earlyReactions"), num("earlyViews")), later = rate(num("laterReactions"), num("laterViews"));
      if (early === null || later === null) return { inline: bars, chart: axisBars };
      return {
        inline: bars,
        chart: <>
          <ColumnChart testId="early-pack-chart" yTitle="реакций на 1 000 просмотров" format={formatRate}
            label={`Реакций на 1 000 просмотров: в первые часы ${formatRate(early)}, за остаток суток ${formatRate(later)}`}
            data={[
              { label: "первые часы", value: early, text: formatRate(early), accent: true, title: "реакций на 1 000 просмотров в первые часы" },
              { label: "остаток суток", value: later, text: formatRate(later), title: "реакций на 1 000 просмотров за остаток суток" },
            ]} />
          {cohortMedian !== null ? <p className="text-muted-foreground text-xs">Все посты окна вместе. У типичного аккаунта {platformName(platform)} первые
            часы выше остатка суток в {formatTimes(cohortMedian)} раза.</p> : null}
          {axisBars}
        </>,
      };
    }
    case "engagement_shift": {
      const cut = typeof metrics.cut === "string" ? shortDay(metrics.cut) : null;
      const before = num("erBefore"), after = num("erAfter"), viewsBefore = num("medianViewsBefore"), viewsAfter = num("medianViewsAfter");
      if (!cut || before === null || after === null) return { inline: bars, chart: axisBars };
      return {
        inline: <CompareBars title="реакций на 100 просмотров" note={comparisonNote(after, before)} format={formatPercentRate}
          items={[{ label: `с ${cut}`, value: after * 100, text: formatPercentRate(after * 100), accent: true },
            { label: `до ${cut}`, value: before * 100, text: formatPercentRate(before * 100) }]} />,
        chart: <>
          <div className="grid gap-4 sm:grid-cols-2">
            <ColumnChart testId="shift-rate-chart" yTitle="реакций на 100 просмотров" format={formatPercentRate}
              label={`Реакций на 100 просмотров: до ${cut} ${formatPercentRate(before * 100)}, с ${cut} ${formatPercentRate(after * 100)}`}
              data={[{ label: `до ${cut}`, value: before * 100, text: formatPercentRate(before * 100) },
                { label: `с ${cut}`, value: after * 100, text: formatPercentRate(after * 100), accent: true }]} />
            {viewsBefore !== null && viewsAfter !== null ? <ColumnChart testId="shift-views-chart" yTitle="медиана просмотров поста" format={formatCount}
              label={`Медиана просмотров поста: до ${cut} ${formatCount(viewsBefore)}, с ${cut} ${formatCount(viewsAfter)}`}
              data={[{ label: `до ${cut}`, value: viewsBefore, text: formatCount(viewsBefore) },
                { label: `с ${cut}`, value: viewsAfter, text: formatCount(viewsAfter), accent: true }]} /> : null}
          </div>
          {axisBars}
        </>,
      };
    }
    case "night_reactions": {
      const views = num("viewShare"), reactions = num("reactionShare"), start = num("nightStartMsk");
      if (views === null || reactions === null || start === null) return { inline: bars, chart: axisBars };
      const night = `${pad(start)}:00–${pad((start + 6) % 24)}:00 МСК`;
      const items: BarItem[] = [
        { label: "поздних реакций", value: reactions, text: formatPercent(reactions), accent: true },
        { label: "поздних просмотров", value: views, text: formatPercent(views) },
      ];
      return {
        inline: <CompareBars title={`приходится на ночь, ${night}`} note={comparisonNote(reactions, views)} items={items} max={niceShare(reactions)} />,
        chart: <>
          <ColumnChart testId="night-chart" yTitle={`доля ночью, ${night}`} format={formatPercent}
            label={`Ночью приходится ${formatPercent(reactions)} поздних реакций и ${formatPercent(views)} поздних просмотров`}
            data={[{ label: "просмотры", value: views, text: formatPercent(views), title: "доля поздних просмотров ночью" },
              { label: "реакции", value: reactions, text: formatPercent(reactions), accent: true, title: "доля поздних реакций ночью" }]} />
          {axisBars}
        </>,
      };
    }
    case "late_growth": {
      const day = num("medianDay"), late = num("medianLate"), boosted = num("boosted"), posts = num("posts");
      return {
        inline: bars,
        chart: <>
          {axisBars}
          {day !== null && late !== null ? <ColumnChart testId="growth-chart" yTitle="медиана реакций поста" format={formatCount}
            label={`Медиана реакций выросших постов: к суткам ${formatCount(day)}, через 3–14 суток ${formatCount(late)}`}
            data={[{ label: "к 24 ч", value: day, text: formatCount(day) },
              { label: "через 3–14 суток", value: late, text: formatCount(late), accent: true }]} /> : null}
          {boosted !== null && posts !== null ? <p className="text-muted-foreground text-xs">Столбики — посты, у которых реакции выросли
            втрое и больше: {boosted} из {posts}.</p> : null}
        </>,
      };
    }
    case "synchronous_waves": {
      const dates = Array.isArray(metrics.dates) ? metrics.dates.filter((day): day is string => typeof day === "string") : [];
      return {
        inline: bars,
        chart: <>
          {dates.length ? <WaveCalendar start={item.windowStart} end={item.windowEnd} dates={dates} minPosts={10} /> : null}
          {axisBars}
        </>,
      };
    }
    case "view_waves": {
      const share = num("viewShare");
      const single = share !== null ? (axis: boolean) => <CompareBars title="просмотров пришло волнами по стене" max={1} axis={axis} format={formatPercent}
        items={[{ label: "этот аккаунт", value: share, text: formatPercent(share), accent: true }]} /> : null;
      const days = num("days"), hours = num("hours");
      return {
        inline: single?.(false) ?? null,
        chart: <>
          {single?.(true)}
          {days !== null && hours !== null ? <StatTiles items={[{ label: "дней с волнами", value: String(days) }, { label: "часов волн", value: String(hours) },
            ...(num("posts") !== null ? [{ label: "постов в окне", value: String(num("posts")) }] : [])]} /> : null}
        </>,
      };
    }
    case "promotion": {
      const first = typeof metrics.firstDay === "string" ? shortDay(metrics.firstDay) : null;
      const last = typeof metrics.lastDay === "string" ? shortDay(metrics.lastDay) : null;
      const tiles = [
        ...(num("posts") !== null ? [{ label: "постов", value: String(num("posts")) }] : []),
        ...(first && last ? [{ label: "суток подряд", value: `${num("days") ?? "—"} · ${first}–${last}` }] : []),
        ...(num("excessMedian") !== null ? [{ label: "просмотров к норме аккаунта", value: `${formatTimes(num("excessMedian")!)}×` }] : []),
        ...(num("views") !== null ? [{ label: "просмотров за эти сутки", value: formatCount(num("views")!) }] : []),
        ...(num("reactions") !== null ? [{ label: "реакций за эти сутки", value: formatCount(num("reactions")!) }] : []),
      ];
      return { inline: null, chart: tiles.length ? <StatTiles items={tiles} /> : null };
    }
    default:
      return { inline: bars, chart: axisBars };
  }
}

/** Мера находки против площадки: две полосы от нуля в единицах находки. У
 *  находок охвата «типично» — 90-й перцентиль площадки: так их и отбирают. */
function FigureBars({ figure, platform, kind, accent, showGap, axis = false }: {
  figure: Figure; platform: string; kind?: string; accent: boolean; showGap: boolean; axis?: boolean;
}) {
  const percentile = kind === "view_packs" || kind === "level3_share" || kind === "flat_daily_views"
    || kind === "early_response";
  const percent = figure.unit === "percent";
  const typicalLabel = percentile ? `9 из 10 аккаунтов ${platformName(platform)} ≤` : `типичный аккаунт ${platformName(platform)}`;
  const items: BarItem[] = [
    { label: "этот аккаунт", value: figure.value, text: format(figure.value, figure.unit), accent },
    { label: typicalLabel, value: figure.typical, text: format(figure.typical, figure.unit), title: typicalLabel },
  ];
  return <CompareBars title={figure.label} items={items} note={showGap ? comparison(figure) : null} axis={axis}
    max={percent ? 1 : undefined} format={(value) => format(value, figure.unit)} />;
}

function corridorPoints(metrics: Record<string, unknown> | undefined) {
  const raw = metrics?.points72;
  if (!Array.isArray(raw)) return null;
  const points = raw.flatMap((item) => Array.isArray(item) && typeof item[0] === "string" && typeof item[1] === "number"
    ? [{ day: item[0], reactions: item[1] }] : []);
  const dayMinPosts = typeof metrics?.dayMinPosts === "number" ? metrics.dayMinPosts : 3;
  return points.length >= 2 ? { points, dayMinPosts } : null;
}

function TailDetails({ tail }: { tail: NonNullable<TailProfileLoad> }) {
  const view = tailSummary(tail);
  if (!view.metrics) return null;
  return <>
    <p>{view.sentence}</p>
    {view.metrics.days.length ? <DailyShareChart days={view.metrics.days} /> : null}
  </>;
}

const rate = (reactions: number | null, views: number | null) => reactions !== null && views ? (1000 * reactions) / views : null;
const pad = (hour: number) => String(hour).padStart(2, "0");
const platformName = (platform: string) => PLATFORM_LABELS[platform as keyof typeof PLATFORM_LABELS] ?? "площадки";
const formatRate = (value: number) => value < 10 && !Number.isInteger(value) ? value.toFixed(1).replace(".", ",") : String(Math.round(value));
const formatPercentRate = (value: number) => `${value < 10 && !Number.isInteger(value) ? value.toFixed(1).replace(".", ",") : Math.round(value)} %`;
const formatPercent = (value: number) => `${Math.round(value * 100)} %`;
const formatCount = (value: number) => Math.round(value).toLocaleString("ru-RU");
const formatTimes = (value: number) => value < 10 ? value.toFixed(1).replace(".", ",") : String(Math.round(value));
/** Доли ночью малы: ось — до ближайшего «круглого» значения выше большей доли. */
const niceShare = (value: number) => Math.min(1, Math.ceil((value * 1.15) * 10) / 10);
/** «в 3,4 раза больше» — подпись к паре полос. */
function comparisonNote(value: number, base: number): string | null {
  if (!(base > 0)) return null;
  const ratio = value / base;
  if (ratio < 1.5) return null;
  return `в ${formatTimes(ratio)} ${ratio < 10 || [2, 3, 4].includes(Math.round(ratio) % 10) && ![12, 13, 14].includes(Math.round(ratio) % 100) ? "раза" : "раз"} больше`;
}

function format(value: number, unit: Figure["unit"]): string {
  if (unit === "percent") return `${Math.round(value * 100)} %`;
  if (unit === "times") return `${value < 10 ? value.toFixed(value < 1 ? 2 : 1).replace(".", ",") : Math.round(value)}×`;
  return value.toFixed(2).replace(".", ",");
}

const plural = (count: number) => count % 10 === 1 && count % 100 !== 11 ? "находка"
  : count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14) ? "находки" : "находок";
const lower = (text: string) => text.replace(/^./, (letter) => letter.toLowerCase());
