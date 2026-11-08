import { Card } from "@/components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { PLATFORM_LABELS, PLATFORM_LONG_LABELS } from "@/lib/format";
import type { AccountView, PublicationListItem } from "@/lib/types";
import { ChannelSwitch } from "@/components/channel-switch";
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
import { AccountRibbon } from "@/components/account-ribbon";
import { AccountStanding, AccountTiming } from "@/components/account-compare-lazy";
import { Tile, change } from "@/components/account-tile";
import { AccountPeriodTiles } from "@/components/account-period-tiles";
import { Eye, FileText, Heart, History, MessageCircle, Trophy } from "lucide-react";
import { Suspense } from "react";
import { PageTitle } from "@/components/page-title";


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
    <AccountRibbon label="Показатели аккаунта" slides={[
      { id: "overview", label: "Обзор", width: "w-[min(86vw,29rem)]", content:
        <section aria-label="Сводка вуза" className="bg-card grid h-full min-w-0 grid-cols-2 content-start gap-2.5 rounded-xl border p-3 text-sm">
          {stats ? null : <p className="col-span-2 text-xs leading-relaxed text-muted-foreground">Сводка публикаций ещё не рассчитана.</p>}
          {stats ? <>
          <AccountPeriodTiles stats={stats} platformLabel={PLATFORM_LONG_LABELS[account.platform]}
            telegram={telegram} primary={primary}
            icons={{ posts: <FileText />, reactions: <Heart />, comments: <MessageCircle />, views: <Eye /> }}
            monitored={<Tile value={String(stats.monitored)} label="с полной историей" icon={<History />}
              note="Публикации, для которых в базе отмечена полная история наблюдений. Показатель относится к аккаунту на выбранной площадке."
              delta={change(stats.monitored, previous.monitored)} deltaLabel="с полной историей за сутки" />}
            rating={<>
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
            </>} />
          </> : null}
          <InstitutionFacts profile={account.institutionProfile} />
        </section> },
      ...(stats ? [{ id: "dynamics", label: "Динамика", width: "w-[min(86vw,46rem)]", content:
        <div className="bg-card h-full min-w-0 rounded-xl border p-1 [&>section]:h-full [&>section]:border-0 [&>section]:bg-transparent">
          <WeeklyTrend key={selectedTrend ?? "unselected"} points={series} primary={primary} selectedDay={selectedDay} selectedTrend={selectedTrend} accountId={account.accountId} />
        </div> }] : []),
      ...(findings || tailProfile ? [{ id: "analysis", label: "Анализ", width: "w-[min(86vw,32rem)]", contained: true, content:
        <Suspense fallback={<div className="bg-card h-full min-h-48 w-full rounded-xl border" role="status" aria-label="Анализ аккаунта загружается" />}>
          <AccountAnalysis findings={findings} tail={tailProfile} platform={account.platform} />
        </Suspense> }] : []),
      { id: "standing", label: "Сравнение", width: "w-[min(86vw,24rem)]", content:
        <AccountStanding institutionId={account.institutionId} platform={account.platform} /> },
      { id: "timing", label: "Время и форматы", width: "w-[min(86vw,40rem)]", content:
        <AccountTiming institutionId={account.institutionId} platform={account.platform} /> },
    ]} />
    <Card className="block p-5 text-sm mt-4 min-w-0 overflow-x-auto">
      <DaySpotlight day={selectedDay} mode={selectedTrend} /><Table className="reveal"><TableHeader><TableRow><TableHead>Публикация</TableHead><TableHead>Опубликовано, МСК</TableHead><TableHead>Возраст</TableHead><TableHead>История</TableHead><TableHead>{telegram ? "Реакции" : primary}</TableHead><TableHead>Просмотры</TableHead><TableHead>Комментарии</TableHead><TableHead>Тип</TableHead>{anomalyLevels ? <TableHead>Анализ динамики</TableHead> : null}</TableRow></TableHeader><TableBody>
      {posts.map((post) => <PublicationRow key={post.publicationId} post={post} account={account} primary={primary}
        level={anomalyLevels ? <AnomalyLevelCell levels={anomalyLevels} publicationId={post.publicationId} /> : null} />)}
      {/* Курсор несёт день и ревизию первой страницы. При выборе другого дня
          страница та же, и без ключа догрузка продолжала бы старый список:
          его курсор API отвергает как чужой, а догруженные строки остаются. */}
      {nextCursor ? <AccountMorePublications key={nextCursor} account={account} primary={primary} cursor={nextCursor} shown={posts.length}
        day={selectedTrend === "total" ? selectedDay : undefined} columns={anomalyLevels ? 9 : 8} withLevels={Boolean(anomalyLevels)} /> : null}
      {!posts.length ? <TableRow><TableCell colSpan={anomalyLevels ? 9 : 8} className="space-y-3 py-10 text-center text-muted-foreground">Публикации ещё не собраны.</TableCell></TableRow> : null}
    </TableBody></Table></Card>
    </NavigationBoundary>
  </>;
}
