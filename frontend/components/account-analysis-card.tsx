"use client";

import { use } from "react";
import { ArrowUpFromLine, ChevronRight, CircleCheck, History, Layers, Moon, Package, ScanLine, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { StatusPill } from "@/components/ui";
import { MethodNote } from "@/components/method-note";
import { tailSummary, type TailProfileLoad } from "@/lib/account-tail";
import { PLATFORM_LABELS } from "@/lib/format";
import type { AccountAnomalyFinding, AccountAnomalyFindings } from "@/lib/types";
import { cn } from "@/lib/utils";
import { figureComparison as comparison } from "@/lib/finding-figure";

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

/** Карточка ленты: находки сразу видны строками с линейкой «типично ↔ этот
 *  аккаунт», а длинное объяснение каждой открывается отдельным окном. */
export function AccountAnalysisCard({ findings, tail, platform }: {
  findings: Promise<FindingsLoad> | null; tail: Promise<TailProfileLoad> | null; platform: string;
}) {
  const loadedFindings = findings ? use(findings) : null;
  const loadedTail = tail ? use(tail) : null;
  const rows = buildRows(loadedFindings, loadedTail);
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
      {rows.length ? (
        <ul className="divide-border -mx-1 mt-2 divide-y">
          {rows.map((row) => <AnalysisRow key={row.key} row={row} platform={platform} />)}
        </ul>
      ) : (
        <p className="text-muted-foreground mt-auto flex items-center gap-1.5 py-6 text-xs">
          <CircleCheck className="size-4" aria-hidden="true" />Признаков, общих для многих постов, не найдено.
        </p>
      )}
    </section>
  );
}

function AnalysisRow({ row, platform }: { row: Row; platform: string }) {
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
          <p className="text-muted-foreground mt-0.5 text-xs leading-relaxed">{row.headline}</p>
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
              {row.figure ? <Ruler figure={row.figure} platform={platform} muted={!row.finding} showGap={row.notable} /> : null}
              <div className="grid gap-3 text-xs leading-relaxed">{row.details}</div>
            </DialogContent>
          </Dialog>
        ) : null}
      </div>
      {row.figure ? <div className="pl-6"><Ruler figure={row.figure} platform={platform} muted={!row.finding} showGap={row.notable} /></div> : null}
    </li>
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
    <figure className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1" aria-label={`${figure.label}: ${format(value, figure.unit)}, типично ${format(typical, figure.unit)}`}>
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

const plural = (count: number) => count % 10 === 1 && count % 100 !== 11 ? "находка"
  : count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14) ? "находки" : "находок";
const lower = (text: string) => text.replace(/^./, (letter) => letter.toLowerCase());
