"use client";

import { use, useState } from "react";
import { ArrowUpFromLine, ChevronRight, CircleCheck, History, Layers, Moon, Package, ScanLine, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { StatusPill } from "@/components/ui";
import { MethodNote } from "@/components/method-note";
import { tailSummary, type TailProfileLoad } from "@/lib/account-tail";
import { PLATFORM_LABELS } from "@/lib/format";
import type { AccountAnomalyFinding, AccountAnomalyFindings } from "@/lib/types";
import { cn } from "@/lib/utils";

export type FindingsLoad = AccountAnomalyFindings | null;

const METHOD = "Закономерности, которые видны только на многих постах сразу. Аккаунт сравнивается с другими "
  + "аккаунтами своей площадки за 30 дней; линейка показывает, где он относительно типичного. «Устойчиво» — "
  + "и в первой, и во второй половине окна. Находки считаются отдельно и не меняют уровни постов; посты, из "
  + "которых складывается находка, ссылаются на неё. Необычное бывает и у живой аудитории: находка сама по "
  + "себе не доказывает искусственное происхождение активности или действия университета.";

const ICONS: Record<string, LucideIcon> = {
  early_pack: Package, regular_reactions: ScanLine, late_growth: TrendingUp, late_engagement: History,
  synchronous_waves: Layers, engagement_shift: ArrowUpFromLine, night_reactions: Moon,
};

type Figure = NonNullable<AccountAnomalyFinding["figure"]>;

/** Строка блока: находка или профиль отклика на старые посты, если находкой он не стал. */
type Row = {
  key: string; title: string; status: string | null; strong: boolean; finding: boolean; notable: boolean;
  headline: string; figure: Figure | null; details: React.ReactNode;
};

/** Один блок вместо двух карточек: свёрнутая строка с находками, по раскрытию —
 *  строки с линейкой «типично ↔ этот аккаунт» и подробностями по требованию. */
export function AccountAnalysisCard({ findings, tail, platform }: {
  findings: Promise<FindingsLoad> | null; tail: Promise<TailProfileLoad> | null; platform: string;
}) {
  const loadedFindings = findings ? use(findings) : null;
  const loadedTail = tail ? use(tail) : null;
  const rows = buildRows(loadedFindings, loadedTail);
  const found = rows.filter((row) => row.finding);
  const notable = rows.filter((row) => !row.finding && row.notable);
  if (!rows.length) return null;
  return (
    <Collapsible render={<section className="bg-card mt-5 min-w-0 rounded-xl border text-sm" id="account-findings"
      aria-labelledby="account-analysis-title" data-testid="account-analysis-card" />}>
      <div className="flex items-center gap-1 pr-3">
        <h2 id="account-analysis-title" className="m-0 min-w-0 flex-1">
          <CollapsibleTrigger data-testid="account-analysis-toggle"
            className="group focus-visible:ring-ring/50 flex w-full items-center gap-2 rounded-xl px-4 py-3 text-left focus-visible:ring-[3px] focus-visible:outline-none">
            <ChevronRight className="text-muted-foreground size-4 shrink-0 transition-transform group-data-[panel-open]:rotate-90" aria-hidden="true" />
            <span className="font-heading shrink-0 font-semibold">Анализ аккаунта</span>
            {found.length
              ? <span className="flex min-w-0 items-center gap-2">
                <StatusPill tone="amber">{found.length} {plural(found.length)}</StatusPill>
                <span className="text-muted-foreground hidden truncate text-xs font-normal sm:inline">
                  {found.map((row) => row.title).join(", ")}
                </span>
              </span>
              : notable.length
                ? <span className="text-muted-foreground flex min-w-0 items-center gap-2 text-xs font-normal">
                  {notable.map((row) => <span key={row.key} className="truncate">{row.title}: {row.status}</span>)}
                </span>
                : <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs font-normal">
                  <CircleCheck className="size-3.5" aria-hidden="true" />находок нет
                </span>}
          </CollapsibleTrigger>
        </h2>
        <MethodNote title="Анализ аккаунта">{METHOD}</MethodNote>
      </div>
      <CollapsibleContent>
        <ul className="divide-border border-border divide-y border-t px-4">
          {rows.map((row) => <AnalysisRow key={row.key} row={row} platform={platform} />)}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

function AnalysisRow({ row, platform }: { row: Row; platform: string }) {
  const [open, setOpen] = useState(false);
  const Icon = ICONS[row.key] ?? History;
  return (
    <Collapsible open={open} onOpenChange={setOpen} render={<li data-testid="account-finding" data-kind={row.key}
      className="grid min-w-0 gap-x-8 gap-y-2 py-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,20rem)] sm:items-center" />}>
      <div className="grid min-w-0 gap-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Icon className={cn("size-4 shrink-0", row.finding ? "text-chart-3" : "text-muted-foreground")} aria-hidden="true" />
          <span className="font-semibold">{row.title}</span>
          {row.status ? <StatusPill tone={row.strong ? "amber" : "neutral"}>{row.status}</StatusPill> : null}
        </div>
        <p className="text-muted-foreground pl-6 text-xs leading-relaxed">
          {row.headline}
          {row.details ? <CollapsibleTrigger className="text-foreground/80 hover:text-foreground focus-visible:ring-ring/50 ml-2 inline-flex items-center gap-0.5 rounded-sm underline-offset-2 hover:underline focus-visible:ring-[3px] focus-visible:outline-none">
            {open ? "скрыть" : "подробнее"}
            <ChevronRight className={cn("size-3 transition-transform", open && "rotate-90")} aria-hidden="true" />
          </CollapsibleTrigger> : null}
        </p>
      </div>
      {row.figure ? <Ruler figure={row.figure} platform={platform} muted={!row.finding} showGap={row.notable} /> : <span />}
      {row.details ? <CollapsibleContent className="grid gap-3 pl-6 text-xs leading-relaxed sm:col-span-2">{row.details}</CollapsibleContent> : null}
    </Collapsible>
  );
}

/** Линейка: где аккаунт относительно типичного аккаунта площадки. Логарифмическая
 *  шкала для отношений и разброса — «вдесятеро» должно выглядеть дальше, чем «вдвое». */
function Ruler({ figure, platform, muted, showGap }: { figure: Figure; platform: string; muted: boolean; showGap: boolean }) {
  const { value, typical } = figure;
  const percent = figure.unit === "percent";
  const scale = (x: number) => percent ? x : Math.log(Math.max(x, 1e-3));
  const low = Math.min(scale(value), scale(typical)), high = Math.max(scale(value), scale(typical));
  const span = Math.max(high - low, percent ? 0.2 : 0.7);
  const pad = span * 0.18;
  const position = (x: number) => ((scale(x) - (low - pad)) / (span + 2 * pad)) * 100;
  const at = position(value), base = position(typical);
  // «Во сколько раз» — только когда отличие и есть вывод; у обычного профиля
  // такая подпись спорила бы со статусом «обычный для площадки».
  const gap = showGap ? comparison(figure) : null;
  return (
    <figure className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1 pl-6 sm:pl-0" aria-label={`${figure.label}: ${format(value, figure.unit)}, типично ${format(typical, figure.unit)}`}>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted-foreground min-w-0 truncate" title={figure.label}>{figure.label}</span>
        <b className={cn("font-heading tabular shrink-0 text-sm", muted ? "text-foreground" : "text-chart-3")}>{format(value, figure.unit)}</b>
      </div>
      <div className="relative h-4" aria-hidden="true">
        <span className="bg-muted absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full" />
        <span className={cn("absolute top-1/2 h-1 -translate-y-1/2 rounded-full", muted ? "bg-muted-foreground/40" : "bg-chart-3/40")}
          style={{ left: `${Math.min(at, base)}%`, width: `${Math.abs(at - base)}%` }} />
        <span className="bg-muted-foreground absolute top-1/2 h-3 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${base}%` }} />
        <span className={cn("border-background absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2",
          muted ? "bg-foreground" : "bg-chart-3")} style={{ left: `${at}%` }} />
      </div>
      <figcaption className="text-muted-foreground flex flex-wrap justify-between gap-x-2 text-[11px] tabular-nums">
        <span className="min-w-0">типично для {PLATFORM_LABELS[platform as keyof typeof PLATFORM_LABELS] ?? "площадки"}: {format(typical, figure.unit)}</span>
        {gap ? <span>{gap}</span> : null}
      </figcaption>
    </figure>
  );
}

function buildRows(findings: FindingsLoad, tail: TailProfileLoad): Row[] {
  const rows: Row[] = (findings?.items ?? []).map((item) => ({
    key: item.kind, title: item.title ?? item.kind, status: item.statusLabel, strong: item.status === 2, finding: true, notable: true,
    headline: item.headline ?? item.summary ?? "", figure: item.figure,
    details: <>
      {item.summary ? <p>{item.summary}.</p> : null}
      {item.kind === "late_engagement" && tail ? <TailDetails tail={tail} /> : null}
      <p className="text-muted-foreground">
        {item.membersCount ? `Постов в находке: ${item.membersCount} — они отмечены на своих страницах. ` : null}
        {item.alternatives ? `Другие объяснения: ${lower(item.alternatives)}.` : null}
      </p>
    </>,
  }));
  // Профиль отклика на старые посты — отдельной строкой, только если находкой он не стал.
  if (tail?.metrics && !rows.some((row) => row.key === "late_engagement")) {
    const view = tailSummary(tail);
    const cohort = tail.metrics.cohort;
    rows.push({
      key: "late_engagement", title: "Отклик на старые посты", status: view.label, strong: false, finding: false,
      notable: (tail.level ?? 0) >= 1,
      headline: tail.level === 0 ? "Как у большинства аккаунтов площадки"
        : cohort?.rank !== undefined ? `Выше, чем у ${Math.round(cohort.rank * 100)} % аккаунтов площадки`
          : view.abstainText ?? view.label,
      figure: tail.metrics.ratio !== null && cohort?.median != null
        ? { value: tail.metrics.ratio, typical: cohort.median, unit: "times", label: "поздняя доля реакций к ранней", direction: "higher" }
        : null,
      details: <TailDetails tail={tail} />,
    });
  }
  return rows;
}

function TailDetails({ tail }: { tail: NonNullable<TailProfileLoad> }) {
  const view = tailSummary(tail);
  if (!view.metrics) return null;
  return <>
    <p>{view.sentence}</p>
    {view.metrics.days.length ? <DailyStrip days={view.metrics.days} /> : null}
  </>;
}

/** Сутки окна: сколько старых постов получили реакции. Серые — замеров не хватило. */
function DailyStrip({ days }: { days: { day: string; observed: number; active: number; reactions: number }[] }) {
  return <figure className="grid max-w-xl gap-1">
    <div className="flex h-8 items-end gap-[3px]" role="img"
      aria-label={`Сутки с поздними реакциями: ${days.filter((day) => day.active > 0).length} из ${days.length}`}>
      {days.map((day) => {
        const share = day.observed ? day.active / day.observed : 0;
        return <span key={day.day} title={day.observed
          ? `${day.day}: реакции получили ${day.active} из ${day.observed} старых постов, +${day.reactions}`
          : `${day.day}: замеров старых постов не хватило`}
          className={cn("min-w-0 flex-1 rounded-[2px]", day.observed ? "bg-chart-3" : "bg-muted")}
          style={{ height: day.observed ? `${Math.max(10, share * 100)}%` : "100%", opacity: day.observed ? 0.35 + 0.65 * share : 0.5 }} />;
      })}
    </div>
    <figcaption className="text-muted-foreground">Доля старых постов, получивших реакции за сутки</figcaption>
  </figure>;
}

function format(value: number, unit: Figure["unit"]): string {
  if (unit === "percent") return `${Math.round(value * 100)} %`;
  if (unit === "times") return `${value < 10 ? value.toFixed(value < 1 ? 2 : 1).replace(".", ",") : Math.round(value)}×`;
  return value.toFixed(2).replace(".", ",");
}

/** «в 6,8 раза выше» — во сколько раз аккаунт отличается от типичного в сторону находки. */
function comparison(figure: Figure): string | null {
  const { value, typical, unit } = figure;
  if (unit === "percent") return value - typical >= 0.05 ? `+${Math.round((value - typical) * 100)} п. п.` : null;
  const ratio = figure.direction === "lower" ? typical / Math.max(value, 1e-3) : value / Math.max(typical, 1e-3);
  if (!Number.isFinite(ratio) || ratio < 1.5) return null;
  const whole = Math.round(ratio);
  const text = ratio < 10 ? ratio.toFixed(1).replace(".", ",") : String(whole);
  // «в 2,5 раза», «в 23 раза», «в 15 раз»
  const word = ratio < 10 || (whole % 10 >= 2 && whole % 10 <= 4 && (whole % 100 < 12 || whole % 100 > 14)) ? "раза" : "раз";
  return `в ${text} ${word} ${figure.direction === "lower" ? "ниже" : "выше"}`;
}

const plural = (count: number) => count % 10 === 1 && count % 100 !== 11 ? "находка"
  : count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14) ? "находки" : "находок";
const lower = (text: string) => text.replace(/^./, (letter) => letter.toLowerCase());
