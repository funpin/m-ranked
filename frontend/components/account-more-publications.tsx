"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";
import { LevelBadge } from "@/components/anomaly-level-badge";
import { PublicationRow, type PublicationRowAccount } from "@/components/account-publication-row";
import type { AccountLevel } from "@/lib/anomaly";
import type { AccountAnomalyLevels, PublicationListItem } from "@/lib/types";

const PAGE = 100;

type AccountPublicationsPage = { items: PublicationListItem[]; nextCursor?: string | null };

async function json<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { accept: "application/json" } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return await response.json() as T;
}

/** Догрузка публикаций аккаунта страницами по сто — до первой публикации в
 *  базе. Курсор закреплён за ревизией первой страницы, поэтому продолжение
 *  не теряет и не повторяет строк, даже если сбор тем временем добавил посты.
 *  Уровни анализа приходят отдельной картой: endpoint отдаёт по тысяче постов
 *  не новее заданного момента, и новая карта нужна раз в десять страниц. */
export function AccountMorePublications({ account, primary, cursor: initialCursor, day, columns, withLevels, shown }: {
  account: PublicationRowAccount & { accountId: string; legacyId: string | number; legacyType: string };
  primary: string; cursor: string | null; day?: string; columns: number; withLevels: boolean; shown: number;
}) {
  const [posts, setPosts] = useState<PublicationListItem[]>([]);
  const [cursor, setCursor] = useState(initialCursor);
  const [levels, setLevels] = useState<Map<string, AccountLevel> | null>(withLevels ? new Map() : null);
  const [levelsFailed, setLevelsFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  async function more() {
    if (!cursor || loading) return;
    setLoading(true);
    setFailed(false);
    try {
      const query = new URLSearchParams({ legacyType: account.legacyType, limit: String(PAGE), cursor });
      if (day) query.set("day", day);
      const page = await json<AccountPublicationsPage>(
        `/api/v1/accounts/${encodeURIComponent(String(account.legacyId))}/publications?${query}`);
      const missing = page.items.find((item) => item.publicationId && levels && !levels.has(item.publicationId));
      if (withLevels && missing && !levelsFailed) {
        try {
          const loaded = await json<AccountAnomalyLevels>(
            `/api/v1/accounts/${account.accountId}/anomaly-levels?before=${encodeURIComponent(missing.publishedAt)}`);
          setLevels((current) => {
            const next = new Map(current ?? []);
            for (const item of loaded.items) next.set(item.publicationId, item);
            return next;
          });
        } catch {
          // Без уровней строки всё равно нужны: колонка покажет прочерки.
          setLevelsFailed(true);
        }
      }
      setPosts((current) => [...current, ...page.items]);
      setCursor(page.nextCursor ?? null);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  return <>
    {posts.map((post) => <PublicationRow key={post.publicationId} post={post} account={account} primary={primary}
      level={withLevels ? <TableCell data-testid="anomaly-level-cell"><LevelBadge loaded={levelsFailed ? null : levels} publicationId={post.publicationId} /></TableCell> : null} />)}
    {cursor || failed ? <TableRow className="hover:bg-transparent">
      <TableCell colSpan={columns} className="py-4 text-center">
        <Button variant="outline" size="sm" onClick={more} disabled={loading} data-testid="account-publications-more">
          {loading ? "Загрузка…" : failed ? "Не удалось загрузить — повторить" : `Показать ещё ${PAGE}`}
        </Button>
        <p className="mt-2 text-xs text-muted-foreground">Показано {shown + posts.length} · старые публикации грузятся по {PAGE}, пока не закончится история в базе.</p>
      </TableCell>
    </TableRow> : posts.length ? <TableRow className="hover:bg-transparent">
      <TableCell colSpan={columns} className="py-4 text-center text-xs text-muted-foreground">Это все публикации аккаунта в базе.</TableCell>
    </TableRow> : null}
  </>;
}
