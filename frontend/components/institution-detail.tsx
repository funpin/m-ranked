import { accountHref, publicationHref } from "@/lib/entity-routes";
import Link from "@/components/native-link";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { legacyDate, legacyNumber, PLATFORM_LONG_LABELS, publicationLabel } from "@/lib/format";
import type { AccountView, InstitutionView, PublicationListItem } from "@/lib/types";
import { PageHeader, StatusPill } from "@/components/ui";
import { PlatformChip } from "@/components/platform-chip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

export function InstitutionDetail({institution,accounts,posts,accountsTruncated=false}:{institution:InstitutionView;accounts:AccountView[];posts:(PublicationListItem & {account:AccountView})[];accountsTruncated?:boolean}) {
  const telegram=institution.platform === "telegram";
  return <>
    <span data-active-platform={institution.platform} hidden />
    <Button variant="ghost" size="sm" className="mb-3 -ml-2" render={<Link href={`/?platform=${institution.platform}`} prefetch={false} />}>
      <ArrowLeft className="size-4" aria-hidden="true" />К обзору
    </Button>
    <PageHeader
      title={institution.shortName || institution.canonicalName}
      description={`${institution.canonicalName}${institution.platform !== "all" ? ` · ${PLATFORM_LONG_LABELS[institution.platform]}` : ""}`}
    />
    {accountsTruncated ? <p className="text-muted-foreground mb-3 text-sm">Показаны первые 100 аккаунтов учреждения.</p> : null}

    <section className="grid grid-cols-[repeat(auto-fit,minmax(270px,1fr))] gap-4">
      {accounts.map((account) => (
        <Card as="article" data-testid="platform-overview-card" key={account.accountId} className="flex flex-col">
          <CardContent className="flex flex-1 flex-col">
            <PlatformChip platform={account.platform} className="w-fit" />
            <h2 className="font-heading mt-4 text-lg leading-snug font-bold">{account.title || account.username || account.canonicalExternalId}</h2>
            <div className="text-muted-foreground mt-1 text-sm">{telegram && account.username ? `@${account.username} · ` : ""}{legacyNumber(account.stats?.subscriberCount ?? null)} подписчиков</div>
            <div className="border-border mt-auto border-t pt-3.5">
              <div className={cn("font-semibold", account.stats?.lastError ? "text-destructive" : account.stats?.lastCheckedAt ? "text-success" : "text-muted-foreground")}>
                {account.stats?.lastError || (account.stats?.lastCheckedAt ? "Источник опрашивается" : "Ожидает первого опроса")}
              </div>
              <p className="mt-1.5 text-sm">
                <Link className="text-chart-2 underline-offset-2 hover:underline" href={accountHref(account.accountId)} prefetch={false}>Открыть публикации</Link>
                {account.url?.startsWith("https://") ? <> · <a className="text-chart-2 inline-flex items-center gap-1 underline-offset-2 hover:underline" href={account.url} target="_blank" rel="noopener noreferrer">Официальный аккаунт<ExternalLink className="size-3.5 shrink-0" aria-hidden="true" /></a></> : null}
              </p>
            </div>
          </CardContent>
        </Card>
      ))}
      {!accounts.length ? <Card><CardContent className="text-muted-foreground py-6">{telegram ? "Telegram-каналы вуза не добавлены." : "Для выбранной площадки официальный аккаунт не добавлен."}</CardContent></Card> : null}
    </section>

    <Card as="section" className="mt-6">
      <CardHeader className="flex flex-wrap items-start justify-between gap-4">
        <CardTitle as="h2" className="font-heading text-lg">Последние публикации</CardTitle>
        <Badge variant="secondary" className="rounded-full font-semibold tabular">{posts.length}</Badge>
      </CardHeader>
      <CardContent>
        {posts.length ? (
          <div className="w-full overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{telegram ? "Канал" : "Площадка"}</TableHead>
                  <TableHead>Опубликовано</TableHead>
                  <TableHead>Публикация</TableHead>
                  <TableHead>{telegram ? "Реакции" : "Просмотры"}</TableHead>
                  <TableHead>{telegram ? "Просмотры" : "Реакции"}</TableHead>
                  <TableHead>Комментарии</TableHead>
                  {!telegram ? <TableHead>Репосты</TableHead> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {posts.map((post) => (
                  <TableRow key={post.publicationId}>
                    <TableCell>{telegram
                      ? <Link className="text-chart-2 underline-offset-2 hover:underline" href={accountHref(post.account.accountId)} prefetch={false}>{post.account.title || `@${post.account.username}`}</Link>
                      : <PlatformChip platform={post.account.platform} label={post.account.platform.toUpperCase()} />}</TableCell>
                    <TableCell className="tabular">{legacyDate(post.publishedAt,true)}</TableCell>
                    <TableCell>
                      {post.publicationId
                        ? <Link className="text-chart-2 underline-offset-2 hover:underline" href={publicationHref(post.publicationId)} prefetch={false}>{publicationLabel(post.displayExternalId ?? post.externalId,post.account.platform)}</Link>
                        : publicationLabel(post.displayExternalId ?? post.externalId,post.account.platform)}
                      {!telegram && post.publicUrl?.startsWith("https://") ? <> · <a className="text-chart-2 inline-flex items-center gap-1 underline-offset-2 hover:underline" href={post.publicUrl} target="_blank" rel="noopener noreferrer">оригинал<ExternalLink className="size-3 shrink-0" aria-hidden="true" /></a></> : null}
                      {post.deletedAt ? <> · <StatusPill tone="red">удалена</StatusPill></> : null}
                      {post.repost ? <> · <StatusPill tone="neutral">репост</StatusPill></> : null}
                      {post.joint ? <> · <StatusPill tone="blue">+{post.additionalAuthorCount} авт.</StatusPill></> : null}
                    </TableCell>
                    <TableCell className="tabular">{legacyNumber(telegram ? post.reactions.value : post.views.value)}</TableCell>
                    <TableCell className="tabular">{legacyNumber(telegram ? post.views.value : post.reactions.value)}</TableCell>
                    <TableCell className="tabular">{legacyNumber(post.comments.value)}</TableCell>
                    {!telegram ? <TableCell className="tabular">{legacyNumber(post.shares.value)}</TableCell> : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : <p className="text-muted-foreground py-6 text-center">Откройте нужный аккаунт выше, чтобы посмотреть его публикации.</p>}
      </CardContent>
    </Card>
  </>;
}
