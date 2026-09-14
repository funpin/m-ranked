import { accountHref } from "@/lib/entity-routes";
import Link from "@/components/native-link";
import { ExternalLink } from "lucide-react";
import { Icon, type IconName } from "@/components/icon-sprite";
import { DeltaBadge } from "@/components/delta-badge";
import { legacyDate, legacyNumber, PERIOD_SHORT, PLATFORM_LABELS } from "@/lib/format";
import { metricNumber, queryHref } from "@/lib/params";
import type { OverviewItem, OverviewMetric, OverviewPage } from "@/lib/types";
import { overviewStatus } from "@/lib/overview-status";
import { metricEvidence, type AggregateMetric } from "@/lib/metric-evidence";
import { AnimatedNumber } from "@/components/animated-number";
import { MethodNote } from "@/components/method-note";
import { cn } from "@/lib/utils";

/** Каждая площадка узнаётся по своему цвету: строка аккаунта, её метка и
 *  полоса слева красятся одной краской, поэтому в общем режиме карточка
 *  читается без чтения подписей. */
const PLATFORM_TONE: Record<string, string> = {
  telegram: "border-l-platform-telegram bg-platform-telegram/8 text-platform-telegram",
  vk: "border-l-platform-vk bg-platform-vk/8 text-platform-vk",
  max: "border-l-platform-max bg-platform-max/8 text-platform-max",
  rutube: "border-l-platform-rutube bg-platform-rutube/8 text-platform-rutube",
};
const PLATFORM_CHIP: Record<string, string> = {
  telegram: "bg-platform-telegram/15 text-platform-telegram",
  vk: "bg-platform-vk/15 text-platform-vk",
  max: "bg-platform-max/15 text-platform-max",
  rutube: "bg-platform-rutube/15 text-platform-rutube",
};

/** Доля публикаций, у которых внутри окна есть замер. Тонкая полоса отвечает
 *  на вопрос «много это или мало» быстрее, чем два числа рядом, и ничего не
 *  стоит: ни графической библиотеки, ни запроса. */
function ActivityMeter({ active, total, period }: { active: number | null; total: number | null; period: string }) {
  if (!total || active === null) return null;
  const share = Math.min(100, Math.round((active / total) * 100));
  const text = `Замер внутри окна есть у ${active} публикаций из ${total} — ${share}%`;
  return (
    <div className="mt-2.5 cursor-help" tabIndex={0} title={text}
      role="meter" aria-valuenow={share} aria-valuemin={0} aria-valuemax={100} aria-label={text}>
      <div className="bg-muted h-1.5 w-full overflow-hidden rounded-full">
        <div className="bg-chart-2 meter-fill h-full rounded-full" style={{ width: `${share}%` }} />
      </div>
      <small className="text-muted-foreground mt-1 block text-[10px] font-medium tracking-wide uppercase">
        активны {active} из {total} {period}
      </small>
    </div>
  );
}

/** Покрытие площадок как четыре отрезка: заполненность видно, не читая дробь. */
function CoverageMeter({ connected }: { connected: number | null }) {
  return (
    <span className="mt-1.5 flex gap-1" aria-hidden="true">
      {[0, 1, 2, 3].map((index) => (
        <span key={index} className={cn("h-1.5 flex-1 rounded-full", index < (connected ?? 0) ? "bg-chart-2 meter-fill" : "bg-muted")} />
      ))}
    </span>
  );
}

function accountName(item: OverviewItem): string {
  const account = item.accounts[0];
  if (!account) return "Официальный аккаунт не добавлен";
  if (account.username) return `@${account.username}`;
  return account.title || account.canonicalExternalId;
}

/** The slot keeps its height whether or not there is a change to report, so a
 *  grid of cards does not shift as values load. */
/**
 * Изменение против предыдущего такого же периода.
 *
 * Место под плашкой держится всегда, даже когда её нет: иначе карточки в
 * сетке разъезжались бы по высоте в зависимости от того, у кого есть с чем
 * сравнивать. За месяц сравнения нет ни у кого — истории наблюдений пока
 * семнадцать суток, а нужно шестьдесят.
 */
function Trend({ value, label, suffix }: {
  value: OverviewMetric["totalTrend"]; label: string; suffix: string;
}) {
  return (
    <span className="mt-1 block min-h-[22px]">
      <DeltaBadge value={metricNumber(value)} label={`${label} против предыдущего периода (${suffix})`} />
    </span>
  );
}

function MetricCell({ value, label, trend, evidence, suffix }: {
  value: OverviewMetric["total"];
  label: string;
  trend: OverviewMetric["totalTrend"];
  evidence: AggregateMetric;
  suffix:string;
}) {
  const text = metricEvidence(evidence);
  return (
    <span className="grid min-w-0 content-start">
      <b className="font-heading tabular text-[27px] leading-none font-extrabold tracking-tight">
        <AnimatedNumber value={metricNumber(value)} />
      </b>
      {/* Пояснение открывается нажатием на значок, а не наведением на само
          число: под курсором-вопросом было неочевидно, что там что-то есть. */}
      <small className="text-muted-foreground mt-1 flex min-h-[2.7em] items-start gap-1 text-[10px] leading-snug font-medium tracking-wide uppercase">
        {label}
        <span className="relative z-[2] -mt-1 shrink-0"><MethodNote title={label}>{text}</MethodNote></span>
      </small>
      <Trend value={trend} label={label} suffix={suffix} />
    </span>
  );
}

function ActivityBody({ item, integrationWarning, href }: { item: OverviewItem; integrationWarning: OverviewPage["integrationWarning"]; href: string }) {
  const short = PERIOD_SHORT[item.period];
  const primary = item.platform === "vk" || item.platform === "rutube" ? "лайков" : "реакций";
  const suffix=short;
  const status=overviewStatus(item,integrationWarning);
  const badges = <div className="mt-3">
    <div className="flex flex-wrap gap-1.5" aria-label={`Публикации ${short}`}>
    {[
      { label: "Всего публикаций в базе.", value: item.totalPublicationCount, icon: "file-text" as IconName, tone: "bg-muted text-muted-foreground", kind: "" },
      { label: `Публикации из БД с активностью ${short}.`, value: item.activityPublicationCount, icon: "trending-up" as IconName, tone: "bg-chart-2/12 text-chart-2", kind: "activity" },
      { label: `Публикации, вышедшие ${short}.`, value: item.newPublicationCount, icon: "plus" as IconName, tone: "bg-success/12 text-success", kind: "new" },
    ].map(({ label, value, icon, tone, kind }) => (
      <span key={kind} className={cn("inline-flex cursor-help items-center gap-1 rounded-md px-1.5 py-1 text-xs font-bold tabular", tone)} tabIndex={0} title={label} aria-label={`${label} ${value}`}>
        <Icon name={icon} className="size-3.5 shrink-0" /><b>{value}</b>
      </span>
    ))}
    </div>
    <ActivityMeter active={item.activityPublicationCount} total={item.totalPublicationCount} period={short} />
  </div>;
  return <>
    {item.ratingRank ? <span className="bg-chart-2 text-background absolute -top-2.5 -right-1.5 z-[3] cursor-help rounded-full px-2 py-1 text-[10px] font-extrabold whitespace-nowrap shadow-sm" tabIndex={0} title={`Официальное место в М‑Рейтинге ${PLATFORM_LABELS[item.platform]}.`}>М‑Рейтинг {PLATFORM_LABELS[item.platform]} · №{item.ratingRank}</span> : null}
    <div className="min-h-[116px]">
      <h3 className="font-heading flex min-h-[2.7em] items-start gap-1 text-base leading-snug font-bold">
        <Link className="line-clamp-2 no-underline outline-none after:absolute after:inset-0 hover:underline focus-visible:underline" href={href} prefetch={false}>
          {item.shortName || item.canonicalName}
        </Link>
        <span className="relative z-[2] shrink-0"><MethodNote title="Полное название">{item.canonicalName}</MethodNote></span>
      </h3>
      <div className="text-muted-foreground mt-1 truncate text-xs">{accountName(item)}{item.accounts.length ? <> · {legacyNumber(item.subscriberCount)} подписчиков{item.accountCount > 1 ? ` · ещё ${item.accountCount - 1}` : ""}</> : null}</div>
      {/* Бейджи стоят внутри блока фиксированной высоты для всех площадок:
          когда они выносились наружу, у ВК, MAX и RuTube тот же блок
          резервировал 116 пикселей и оставался пустым. */}
      {badges}
    </div>
    <div className="my-4 grid flex-1 grid-cols-2 content-center gap-x-5 gap-y-3">
      <MetricCell suffix={suffix} value={item.reactions.total} label={`${primary} ${short}`} trend={item.reactions.totalTrend} evidence={item.reactions.totalMetadata} />
      <MetricCell suffix={suffix} value={item.views.total} label={`просмотров ${short}`} trend={item.views.totalTrend} evidence={item.views.totalMetadata} />
      <MetricCell suffix={suffix} value={item.reactions.median} label={`медиана прироста ${primary}`} trend={item.reactions.medianTrend} evidence={item.reactions.medianMetadata} />
      <MetricCell suffix={suffix} value={item.views.median} label="медиана прироста просмотров" trend={item.views.medianTrend} evidence={item.views.medianMetadata} />
    </div>
    <div className="border-border mt-auto min-h-[67px] border-t pt-3.5">
      <div className={cn("font-semibold", status.kind === "ok" ? "text-success" : status.kind === "warn" ? "text-warning" : status.kind === "bad" ? "text-destructive" : "text-muted-foreground")}>{status.text}</div>
      <div className="text-muted-foreground mt-0.5 text-xs">Последний опрос: {item.lastCheckedAt ? legacyDate(item.lastCheckedAt, true) : "ещё не выполнялся"}</div>
    </div>
  </>;
}

function AllPlatformsBody({ item }: { item: OverviewItem }) {
  const status=overviewStatus(item);
  return (
    <>
      {item.ratingRank ? <span className="bg-chart-2 text-background absolute -top-2.5 -right-1.5 z-[3] cursor-help rounded-full px-2 py-1 text-[10px] font-extrabold whitespace-nowrap shadow-sm" tabIndex={0} title="Официальное место в М‑Рейтинге: Общий.">М‑Рейтинг Общий · №{item.ratingRank}</span> : null}
      <div>
        <h3 className="font-heading flex min-h-[2.7em] items-start gap-1 text-base leading-snug font-bold">
          <span className="line-clamp-2">{item.shortName || item.canonicalName}</span>
          <span className="shrink-0"><MethodNote title="Полное название">{item.canonicalName}</MethodNote></span>
        </h3>
      </div>
      {item.accounts.length ? (
        <div className="my-4 grid gap-1.5">
          {[...item.accounts].sort((a,b)=>a.platform.localeCompare(b.platform)).map((account) => {
            const name = account.title || account.username || account.canonicalExternalId;
            return (
              <div className={cn("flex min-w-0 items-center gap-2 rounded-md border-l-[3px] px-2 py-2", PLATFORM_TONE[account.platform] ?? "bg-muted/60")} key={account.accountId}>
                <span className={cn("inline-block min-w-[66px] rounded-md px-1.5 py-0.5 text-center text-[11px] font-black", PLATFORM_CHIP[account.platform] ?? "bg-muted text-muted-foreground")}>{PLATFORM_LABELS[account.platform]}</span>
                {account.url
                  ? <a className="inline-flex min-w-0 items-center gap-1 truncate hover:underline" href={account.url} target="_blank" rel="noopener noreferrer">{name}<ExternalLink className="size-3.5 shrink-0" aria-hidden="true" /></a>
                  : <span className="min-w-0 truncate">{name}</span>}
              </div>
            );
          })}
        </div>
      ) : <div className="text-muted-foreground py-4">Официальный аккаунт этой площадки пока не подтверждён.</div>}
      <div className="my-3.5 grid grid-cols-2 gap-3">
        <span className="grid min-w-0 gap-0.5"><b className="font-heading tabular text-[27px] leading-none font-extrabold tracking-tight">{item.connectedPlatformCount}/4</b><small className="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">площадок подключено</small><CoverageMeter connected={item.connectedPlatformCount} /></span>
        <span className="grid min-w-0 gap-0.5"><b className="font-heading tabular text-[27px] leading-none font-extrabold tracking-tight">{item.accountCount}</b><small className="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">аккаунтов добавлено</small></span>
      </div>
      <div className="border-border mt-auto min-h-[67px] border-t pt-3.5">
        <div className={cn("font-semibold", status.kind === "ok" ? "text-success" : status.kind === "warn" ? "text-warning" : status.kind === "bad" ? "text-destructive" : "text-muted-foreground")}>{status.text}</div>
      </div>
    </>
  );
}

function activityHref(item: OverviewItem): string {
  if (item.platform === "telegram") {
    return accountHref(item.entityId);
  }
  if (item.accountCount === 1 && item.accounts[0]?.accountId) {
    return accountHref(item.accounts[0].accountId);
  }
  return queryHref(item.legacyRoute || `/institutions/${item.institutionLegacyId}`, {
    platform: item.platform,
  });
}

const CARD = "bg-card text-card-foreground relative z-[1] flex min-h-[470px] min-w-0 flex-col rounded-xl border p-5 pt-6 shadow-sm transition-[transform,box-shadow] duration-200";

export function OverviewCard({ item, integrationWarning }: { item: OverviewItem; integrationWarning: OverviewPage["integrationWarning"] }) {
  if (item.platform === "all") {
    return <article data-testid="platform-overview-card" className={cn(CARD, "min-h-[310px]")}><AllPlatformsBody item={item} /></article>;
  }
  // Карточка перестала быть одной большой ссылкой: ссылка — название, а она
  // растянута на всю карточку. Так внутри помещаются настоящие кнопки с
  // пояснениями, а раньше приходилось обходиться подсказкой по наведению,
  // отчего курсор над названием и числами превращался в вопросительный знак.
  return (
    <article
      data-testid="platform-overview-card"
      className={cn(CARD, "hover:border-ring/40 focus-within:border-ring/40 hover:z-30 hover:-translate-y-0.5 hover:shadow-lg")}
    >
      <ActivityBody item={item} integrationWarning={integrationWarning} href={activityHref(item)} />
    </article>
  );
}
