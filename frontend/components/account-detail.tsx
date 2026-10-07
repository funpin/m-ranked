import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { PLATFORM_LABELS, PLATFORM_LONG_LABELS } from "@/lib/format";
import { metricEvidence } from "@/lib/metric-evidence";
import type { AccountView, PublicationListItem } from "@/lib/types";
import { ChannelSwitch } from "@/components/channel-switch";
import { DeltaBadge, type DeltaTone } from "@/components/delta-badge";
import { WeeklyTrend } from "@/components/weekly-trend";
import { NavigationBoundary } from "@/components/navigation-boundary";
import { AccountSkeleton } from "@/components/skeletons";
import { DaySpotlight } from "@/components/day-spotlight";
import { AnomalyLevelCell } from "@/components/anomaly-level-cell";
import { PublicationRow } from "@/components/account-publication-row";
import { AccountMorePublications } from "@/components/account-more-publications";
import type { AccountLevelsLoad } from "@/lib/anomaly";
import type { TailProfileLoad } from "@/lib/account-tail";
import type { FindingsLoad } from "@/components/account-analysis-card";
import { AccountAnalysis } from "@/components/account-analysis-lazy";
import { InstitutionFacts } from "@/components/institution-facts";
import { SummaryTile } from "@/components/summary-tile";
import { FileText, History, Heart, MessageCircle, Eye, Trophy } from "lucide-react";
import { Suspense, type ReactNode } from "react";
import { PageTitle } from "@/components/page-title";


function Tile({ value, label, icon, note, delta, tone, deltaLabel, footer }: {
  value: string; label: string; icon: ReactNode; note?: string;
  delta?: number | null; tone?: DeltaTone; deltaLabel?: string; footer?: ReactNode;
}) {
  return (
    <SummaryTile value={value} label={label} icon={icon} note={note} footer={footer}
      trailing={<DeltaBadge value={delta} tone={tone} label={deltaLabel ?? label} />} />
  );
}

/** Разница, когда обе величины известны. Иначе сравнивать не с чем. */
function change(current: number | null | undefined,
                previous: number | null | undefined): number | null {
  if (current === null || current === undefined) return null;
  if (previous === null || previous === undefined) return null;
  return current - previous;
}

export function AccountDetail({ account, posts, nextCursor = null, siblings = [], selectedDay, selectedTrend, anomalyLevels = null, tailProfile = null, findings = null }: { account: AccountView; posts: PublicationListItem[]; nextCursor?: string | null; siblings?: readonly AccountView[]; selectedDay?: string; selectedTrend?: "median" | "total"; anomalyLevels?: Promise<AccountLevelsLoad> | null; tailProfile?: Promise<TailProfileLoad> | null; findings?: Promise<FindingsLoad> | null }) {
  const name = account.title || account.institutionShortName || account.institutionName;
  const institutionName = account.institutionName.trim();
  const showInstitutionName = institutionName !== name.trim();
  const stats = account.stats;
  const telegram = account.platform === "telegram";
  const series = stats?.dailySeries ?? [];
  const previous = stats?.previous ?? {
    postCount: null, monitored: null, medianReactions: null, medianViews: null,
    medianComments: null, ratingRank: null, ratingPeriod: null,
  };
  const primary = account.platform === "vk" || account.platform === "rutube" ? "лайков" : "реакций";
  return <><span data-active-platform={account.platform} hidden />
    <header className="mb-4 min-w-0">
      <h1 className="font-heading text-2xl font-semibold tracking-tight wrap-break-word sm:text-3xl"><PageTitle text={name} />{account.username ? <> <span className="text-muted-foreground">@{account.username}</span></> : null}</h1>
      {showInstitutionName ? <p data-testid="institution-full-name" className="mt-1 max-w-4xl text-sm leading-relaxed text-muted-foreground sm:text-base">{institutionName}</p> : null}
    </header>
    <ChannelSwitch accounts={siblings} currentId={account.accountId} />
    {/* Заголовок и переключатель площадок остаются на месте, а блоки с
        данными подменяются заготовкой — так же, как при смене фильтра в
        обзоре и при переходе между постами. */}
    <NavigationBoundary fallback={<AccountSkeleton chrome={false} />}>
    <Card className="block p-4 text-sm sm:p-5">
      {stats ? null : <p className="mb-3 text-xs leading-relaxed text-muted-foreground">Сводка публикаций ещё не рассчитана.</p>}
      <div className="grid min-w-0 items-stretch gap-4 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <section aria-label="Сводка вуза" className="grid min-w-0 grid-cols-2 gap-2.5 sm:grid-cols-4 xl:grid-cols-2">
          {stats ? <>
          <Tile value={String(stats.postCount)} label="публикаций в базе" icon={<FileText />}
            note={`Публикации ${PLATFORM_LONG_LABELS[account.platform]} в базе за последние ${stats.retentionDays} дней.${telegram ? "" : " Метрики, которые площадка не отдаёт, показаны прочерком."}`}
            delta={change(stats.postCount, previous.postCount)} deltaLabel="публикаций за сутки" />
          <Tile value={String(stats.monitored)} label="с полной историей" icon={<History />}
            note="Публикации, для которых в базе отмечена полная история наблюдений. Показатель относится к аккаунту на выбранной площадке."
            delta={change(stats.monitored, previous.monitored)} deltaLabel="с полной историей за сутки" />
          <Tile value={stats.medianReactions.value === null ? "—" : String(Math.trunc(stats.medianReactions.value))}
            label={`медиана ${primary}`} icon={<Heart />} note={metricEvidence(stats.medianReactions)}
            delta={change(stats.medianReactions.value, previous.medianReactions)} />
          <Tile value={stats.medianComments.value === null ? "—" : String(Math.trunc(stats.medianComments.value))}
            label="медиана комментариев" icon={<MessageCircle />} note={metricEvidence(stats.medianComments)}
            delta={change(stats.medianComments.value, previous.medianComments)} />
          <Tile value={stats.medianViews.value === null ? "—" : String(Math.trunc(stats.medianViews.value))}
            label="медиана просмотров" icon={<Eye />} note={metricEvidence(stats.medianViews)}
            delta={change(stats.medianViews.value, previous.medianViews)} />
          {/* Место в рейтинге сравнивается с прошлым опубликованным месяцем, а
              не с прошлыми сутками: рейтинг выходит раз в месяц. И знак у него
              читается наоборот — подняться значит уменьшить номер. */}
          <Tile value={stats.ratingRank ? `№${stats.ratingRank}` : "—"}
            icon={<Trophy />}
            label={`М‑Рейтинг ${PLATFORM_LABELS[account.platform]}`}
            footer={stats.ratingPeriod ?? undefined}
            note={`Официальное место в М‑Рейтинге ${PLATFORM_LABELS[account.platform]}${stats.ratingPeriod ? ` за период «${stats.ratingPeriod}»` : ""}.`}
            delta={change(stats.ratingRank, previous.ratingRank)} tone="rank"
            deltaLabel={previous.ratingPeriod ? `место против периода «${previous.ratingPeriod}»` : "место в рейтинге"} />
          </> : null}
          <InstitutionFacts profile={account.institutionProfile} />
        </section>
        {stats ? <WeeklyTrend key={selectedTrend ?? "unselected"} points={series} primary={primary} selectedDay={selectedDay} selectedTrend={selectedTrend} accountId={account.accountId} /> : null}
      </div>
    </Card>
    {findings || tailProfile ? <Suspense fallback={<Skeleton className="mt-5 h-12 w-full rounded-xl" aria-label="Анализ аккаунта загружается" />}>
      <AccountAnalysis findings={findings} tail={tailProfile} platform={account.platform} />
    </Suspense> : null}
    <Card className="block p-5 text-sm mt-5 min-w-0 overflow-x-auto">
      <DaySpotlight day={selectedDay} mode={selectedTrend} /><Table className="reveal"><TableHeader><TableRow><TableHead>Публикация</TableHead><TableHead>Опубликовано, МСК</TableHead><TableHead>Возраст</TableHead><TableHead>История</TableHead><TableHead>{telegram ? "Реакции" : primary}</TableHead><TableHead>Просмотры</TableHead><TableHead>Комментарии</TableHead><TableHead>Тип</TableHead>{anomalyLevels ? <TableHead>Анализ динамики</TableHead> : null}</TableRow></TableHeader><TableBody>
      {posts.map((post) => <PublicationRow key={post.publicationId} post={post} account={account} primary={primary}
        level={anomalyLevels ? <AnomalyLevelCell levels={anomalyLevels} publicationId={post.publicationId} /> : null} />)}
      {nextCursor ? <AccountMorePublications account={account} primary={primary} cursor={nextCursor} shown={posts.length}
        day={selectedTrend === "total" ? selectedDay : undefined} columns={anomalyLevels ? 9 : 8} withLevels={Boolean(anomalyLevels)} /> : null}
      {!posts.length ? <TableRow><TableCell colSpan={anomalyLevels ? 9 : 8} className="space-y-3 py-10 text-center text-muted-foreground">Публикации ещё не собраны.</TableCell></TableRow> : null}
    </TableBody></Table></Card>
    </NavigationBoundary>
  </>;
}
