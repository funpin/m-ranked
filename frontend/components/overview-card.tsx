import { Badge } from "@/components/ui/badge";
import { accountHref } from "@/lib/entity-routes";
import Link from "@/components/native-link";
import { ExternalLink } from "lucide-react";
import { Icon, type IconName } from "@/components/icon-sprite";
import { DeltaBadge } from "@/components/delta-badge";
import { formatMetric, formatStat, legacyDate, legacyNumber, PERIOD_SHORT, PLATFORM_LABELS, PLATFORM_LONG_LABELS, plural } from "@/lib/format";
import { metricNumber, queryHref } from "@/lib/params";
import type { OverviewItem, OverviewMetric, OverviewPage } from "@/lib/types";
import { overviewStatus } from "@/lib/overview-status";
import { metricEvidence, type AggregateMetric } from "@/lib/metric-evidence";
import { AnimatedNumber } from "@/components/animated-number";
import { MethodNote } from "@/components/method-note";
import { cn } from "@/lib/utils";
import { LevelIcon } from "@/components/anomaly-icons";
import { UsersRound } from "lucide-react";

function CardBadges({ item }: { item: OverviewItem }) {
  const counts = item.anomalyCounts;
  const platform = item.platform === "all" ? "Все площадки" : PLATFORM_LABELS[item.platform];
  const findings = counts?.accountFindings;
  if (!item.ratingRank && !counts?.level2 && !counts?.level3 && !findings) return null;
  return <div className="pointer-events-none relative z-[3] -mx-[26px] -mt-[34px] mb-4 flex flex-wrap items-start justify-between gap-1.5">
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Замечания анализа за выбранный период">
      {([3, 2] as const).map(level => {
        const count = level === 3 ? counts?.level3 : counts?.level2;
        if (!count || !Number.isSafeInteger(count) || count < 0) return null;
        const label = level === 3 ? "Признаки искусственной активности" : "Выраженная аномалия";
        const description = `${label}: ${legacyNumber(count)} ${plural(count, "публикация", "публикации", "публикаций")}. ${platform}, ${PERIOD_SHORT[item.period]}. Учитываются публикации, вышедшие за выбранный период, по текущему итоговому уровню анализа.`;
        return <Badge key={level} data-testid={`overview-anomaly-level-${level}`} tabIndex={0}
          aria-label={description} title={description}
          className={cn("pointer-events-auto h-auto cursor-help px-2 py-1 text-[10px] font-extrabold shadow-sm tabular",
            level === 3 ? "bg-destructive/12 text-destructive" : "bg-warning/15 text-warning")}>
          <LevelIcon level={level} /><span>{legacyNumber(count)}</span>
        </Badge>;
      })}
      {findings && Number.isSafeInteger(findings) && findings > 0 ? (() => {
        // Аккаунтные находки — закономерность аккаунта, а не публикации:
        // отдельный значок, в счётчики уровней постов они не входят.
        const description = `Аккаунтные находки: ${legacyNumber(findings)}. ${platform}. Закономерность на многих постах аккаунта за 30 дней относительно аккаунтов площадки; уровни публикаций не меняет.`;
        return <Badge data-testid="overview-account-findings" tabIndex={0} aria-label={description} title={description}
          className="pointer-events-auto h-auto cursor-help bg-chart-3/15 px-2 py-1 text-[10px] font-extrabold text-chart-3 shadow-sm tabular">
          <UsersRound aria-hidden="true" /><span>{legacyNumber(findings)}</span>
        </Badge>;
      })() : null}
    </div>
    {item.ratingRank ? <Badge className="pointer-events-auto ml-auto h-auto cursor-help bg-chart-2 px-2 py-1 text-[10px] font-extrabold text-background shadow-sm"
      tabIndex={0} title={`Официальное место в М‑Рейтинге ${item.platform === "all" ? "Общий" : platform}.`}>
      М‑Рейтинг {item.platform === "all" ? "Общий" : platform} · №{item.ratingRank}
    </Badge> : null}
  </div>;
}

/** Цветные ссылки сохраняют узнаваемость площадок без длинного списка аккаунтов. */
const PLATFORM_CHIP: Record<string, string> = {
  telegram: "border-platform-telegram/30 text-platform-telegram dark:bg-platform-telegram/15",
  vk: "border-platform-vk/30 text-platform-vk dark:bg-platform-vk/15",
  max: "border-platform-max/30 text-platform-max dark:bg-platform-max/15",
  rutube: "border-platform-rutube/30 text-platform-rutube dark:bg-platform-rutube/15",
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

function accountName(item: OverviewItem): string {
  const account = item.accounts[0];
  if (!account) return "Официальный аккаунт не добавлен";
  if (account.username) return `@${account.username}`;
  return account.title || account.canonicalExternalId;
}

function MetricCell({ value, label, icon, description, trend, evidence, suffix, note }: {
  value: OverviewMetric["total"];
  label: string;
  icon: IconName;
  description: string;
  trend: OverviewMetric["totalTrend"];
  evidence: AggregateMetric;
  suffix:string;
  note?: string;
}) {
  const number = metricNumber(value);
  const exact = formatMetric(value);
  return (
    <div className="@container grid min-w-0 content-start justify-items-start gap-1.5">
      <div className="text-muted-foreground flex w-full items-center justify-between gap-1 text-[11px] leading-none">
        <span className="inline-flex min-w-0 items-center gap-1" title={description}>
          <Icon name={icon} className={cn("size-3.5 shrink-0", label !== "Медиана" && "hidden @min-[128px]:block")} /><span>{label}</span>
        </span>
        <span className="relative z-[2] shrink-0"><MethodNote title={description}>
          {note ? <><p>{note}</p><p>{metricEvidence(evidence)}</p></> : metricEvidence(evidence)}
        </MethodNote></span>
      </div>
      <b className={cn("font-heading tabular whitespace-nowrap leading-none font-extrabold tracking-tight",
        exact.length >= 7 ? "text-[22px]" : "text-[27px]")} title={exact} aria-label={`${description}: ${exact}`}>
        {number !== null && Math.abs(number) >= 1_000_000 ? formatStat(number) : <AnimatedNumber value={number} />}
      </b>
      <DeltaBadge value={metricNumber(trend)} label={`${description} против предыдущего периода (${suffix})`} />
    </div>
  );
}

const pollTimestamp = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
});

function StatusFooter({ item, integrationWarning }: { item: OverviewItem; integrationWarning?: OverviewPage["integrationWarning"] }) {
  const status = overviewStatus(item, integrationWarning);
  const label = item.platform === "all" && status.kind === "ok" ? `${item.connectedPlatformCount}/4 площадки`
    : status.kind === "ok" ? "Активен"
    : status.kind === "bad" ? "Ошибка опроса"
    : !item.accountCount ? "Нет аккаунта"
    : !item.enabledAccountCount ? "Отключён"
    : status.kind === "warn" ? "Нужна настройка" : "Ожидание опроса";
  const date = item.lastCheckedAt ? new Date(item.lastCheckedAt) : null;
  const validDate = date && Number.isFinite(date.getTime());
  const fullPoll = validDate ? `Последний опрос${item.platform === "all" ? " среди аккаунтов вуза" : ""}: ${legacyDate(item.lastCheckedAt, true)}` : "Опрос ещё не выполнялся";
  return <footer data-testid="overview-status" className="border-border mt-auto flex items-center justify-between gap-2 border-t pt-3 text-[11px] leading-5 whitespace-nowrap">
    <span title={status.text} className={cn("inline-flex items-center gap-1.5 font-medium",
      status.kind === "ok" ? "text-success" : status.kind === "warn" ? "text-warning" : status.kind === "bad" ? "text-destructive" : "text-muted-foreground")}>
      <span className="size-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" />{label}
    </span>
    {validDate
      ? <time dateTime={item.lastCheckedAt!} title={fullPoll} aria-label={fullPoll} className="text-muted-foreground tabular text-[10px]">
          {pollTimestamp.format(date).replace(", ", " · ")} МСК
        </time>
      : <span className="text-muted-foreground text-[10px]" title={fullPoll}>Опросов нет</span>}
  </footer>;
}

function PublicationActivity({ item }: { item: OverviewItem }) {
  const short = PERIOD_SHORT[item.period];
  return <div className="mt-3">
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
}

function ActivityBody({ item, integrationWarning, href }: { item: OverviewItem; integrationWarning: OverviewPage["integrationWarning"]; href: string }) {
  const short = PERIOD_SHORT[item.period];
  const primary = item.platform === "vk" || item.platform === "rutube" ? "лайков" : "реакций";
  const primaryLabel = item.platform === "vk" || item.platform === "rutube" ? "Лайки" : "Реакции";
  return <>
    <CardBadges item={item} />
    <div>
      <h3 className="font-heading flex items-start gap-1 text-base leading-snug font-bold">
        <Link className="line-clamp-2 no-underline outline-none after:absolute after:inset-0 hover:underline focus-visible:underline" href={href} prefetch={false}>
          {item.shortName || item.canonicalName}
        </Link>
        <span className="relative z-[2] shrink-0"><MethodNote title="Полное название">{item.canonicalName}</MethodNote></span>
      </h3>
      <div className="text-muted-foreground mt-1 truncate text-xs">{accountName(item)}{item.accounts.length ? <> · {legacyNumber(item.subscriberCount)} подписчиков{item.accountCount > 1 ? ` · ещё ${item.accountCount - 1}` : ""}</> : null}</div>
      <PublicationActivity item={item} />
    </div>
    <div className="my-4 grid flex-1 content-start gap-4">
      <section aria-label={`Прирост ${short}`}>
        <div className="grid grid-cols-2 gap-x-5">
          <MetricCell icon="heart" suffix={short} value={item.reactions.total} label={primaryLabel} description={`Прирост ${primary} ${short}`} trend={item.reactions.totalTrend} evidence={item.reactions.totalMetadata} />
          <MetricCell icon="eye" suffix={short} value={item.views.total} label="Просмотры" description={`Прирост просмотров ${short}`} trend={item.views.totalTrend} evidence={item.views.totalMetadata} />
        </div>
      </section>
      <section aria-label="Медиана прироста" className="border-border/60 border-t pt-3">
        <div className="grid grid-cols-2 gap-x-5">
          <MetricCell icon="heart" suffix={short} value={item.reactions.median} label="Медиана" description={`Медиана прироста ${primary} ${short}`} trend={item.reactions.medianTrend} evidence={item.reactions.medianMetadata} />
          <MetricCell icon="eye" suffix={short} value={item.views.median} label="Медиана" description={`Медиана прироста просмотров ${short}`} trend={item.views.medianTrend} evidence={item.views.medianMetadata} />
        </div>
      </section>
    </div>
    <StatusFooter item={item} integrationWarning={integrationWarning} />
  </>;
}

function AllPlatformsBody({ item }: { item: OverviewItem }) {
  const short = PERIOD_SHORT[item.period];
  const platformOrder = {telegram:0, vk:1, max:2, rutube:3};
  const note = "Суммарный прирост по всем официальным аккаунтам вуза за выбранный период. Учитываются доступные замеры; недоступные метрики не заменяются нулями. Реакции включают лайки в соцсетях, где используется этот показатель.";
  const followers = metricNumber(item.subscriberCount);
  return (
    <>
      <CardBadges item={item} />
      <div>
        <h3 className="font-heading flex items-start gap-1 text-base leading-snug font-bold">
          <span className="line-clamp-2">{item.shortName || item.canonicalName}</span>
          <span className="shrink-0"><MethodNote title="Полное название">{item.canonicalName}</MethodNote></span>
        </h3>
        <div className="text-muted-foreground mt-1 flex items-center gap-1 text-xs">
          <span><b className="text-foreground tabular font-semibold" title={formatMetric(followers)}>{followers === null ? "—" : formatStat(followers)}</b> подписчиков всего</span>
          <MethodNote title="Подписчики во всех соцсетях">Сумма последних доступных замеров подписчиков официальных аккаунтов вуза. Один человек может быть подписан на несколько соцсетей, поэтому это число подписок, а не уникальных людей.</MethodNote>
        </div>
      </div>
      {item.accounts.length ? (
        <div className="mt-2.5 flex flex-wrap gap-1.5" role="group" aria-label="Официальные соцсети вуза">
          {[...item.accounts].sort((a,b)=>platformOrder[a.platform]-platformOrder[b.platform] || a.accountId.localeCompare(b.accountId)).map((account) => {
            const name = account.title || account.username || account.canonicalExternalId;
            const title = `${PLATFORM_LONG_LABELS[account.platform]} · ${name}${account.enabled ? "" : " · отслеживание отключено"}`;
            const className = cn("inline-flex min-h-7 items-center gap-1 rounded-md border px-2 text-[10px] font-bold",
              account.enabled ? PLATFORM_CHIP[account.platform] : "border-border border-dashed text-muted-foreground");
            const label = account.platform === "rutube" ? "RT" : PLATFORM_LABELS[account.platform];
            return account.url
              ? <a key={account.accountId} className={cn(className,"transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none")}
                  href={account.url} target="_blank" rel="noopener noreferrer" title={title} aria-label={`${title}. Открыть официальное сообщество`}>
                  {label}<ExternalLink className="size-3 shrink-0" aria-hidden="true" />
                </a>
              : <span key={account.accountId} className={className} title={`${title} · ссылка не указана`}>{label}</span>;
          })}
        </div>
      ) : <p className="text-muted-foreground mt-2.5 text-xs">Официальные аккаунты пока не добавлены.</p>}
      <PublicationActivity item={item} />
      <section aria-label={`Прирост ${short}`} className="my-4 flex-1">
        <div className="grid grid-cols-2 gap-x-5 gap-y-4">
          {([
            ["views", "Просмотры", "просмотров", "eye"],
            ["reactions", "Реакции", "лайков и реакций", "heart"],
            ["comments", "Комментарии", "комментариев", "message-circle"],
            ["shares", "Репосты", "репостов", "repeat-2"],
          ] as const).map(([key,label,description,icon]) => <MetricCell key={key} icon={icon} suffix={short}
            value={item[key].total} label={label} description={`Прирост ${description} ${short} · все соцсети`}
            trend={item[key].totalTrend} evidence={item[key].totalMetadata} note={note} />)}
        </div>
      </section>
      <StatusFooter item={item} />
    </>
  );
}

function activityHref(item: OverviewItem): string {
  if (item.platform === "telegram") {
    return accountHref(item.entityId);
  }
  if (item.accounts[0]?.accountId) {
    return accountHref(item.accounts[0].accountId);
  }
  return queryHref("/review", { platform: item.platform });
}

const CARD = "bg-card text-card-foreground relative z-[1] flex min-w-0 flex-col rounded-xl border p-5 pt-6 shadow-sm transition-[transform,box-shadow] duration-200";

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
