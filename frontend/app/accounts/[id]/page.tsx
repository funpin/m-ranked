import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountDetail } from "@/components/account-detail";
import { ApiFailureState } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { loadAccountPublications, reportDetailFailure } from "@/lib/detail-data";
import { accountHref, UUID_PATTERN } from "@/lib/entity-routes";
import { PLATFORM_LONG_LABELS } from "@/lib/format";
import type { AccountView } from "@/lib/types";
import { anomalyReportVisible } from "@/lib/anomaly-visibility";
import type { AccountLevelsLoad } from "@/lib/anomaly";
import type { TailProfileLoad } from "@/lib/account-tail";
import type { FindingsLoad } from "@/components/account-findings-card";

export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }>; searchParams: Promise<{ day?: string | string[]; trend?: string | string[] }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  if (!UUID_PATTERN.test(id)) notFound();
  try {
    const account = await api.account(id);
    const name = account.title || account.username || account.institutionName;
    return { title: `${name}: ${PLATFORM_LONG_LABELS[account.platform]}`,
      description: `Публикации и статистика аккаунта ${name}.`,
      alternates: { canonical: accountHref(account.accountId) } };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return { title: "Аккаунт", alternates: { canonical: accountHref(id) } };
  }
}

export default async function AccountPage({ params, searchParams }: Props) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  if (!UUID_PATTERN.test(id)) notFound();
  let account;
  let posts;
  let selectedDay: string | undefined;
  let selectedTrend: "median" | "total" | undefined;
  let siblings: AccountView[] = [];
  // Уровни анализа страница не ждёт: таблица приходит сразу, колонка
  // дорисовывается следом. Сбой анализа — прочерки, а не ошибка страницы.
  const levels: Promise<AccountLevelsLoad> | null = anomalyReportVisible()
    ? api.accountAnomalyLevels(id).then(
      (body) => new Map(body.items.map((item) => [item.publicationId, item])), () => null)
    : null;
  const tail: Promise<TailProfileLoad> | null = anomalyReportVisible()
    ? api.accountTailProfile(id).catch(() => null)
    : null;
  const findings: Promise<FindingsLoad> | null = anomalyReportVisible()
    ? api.accountAnomalyFindings(id).catch(() => null)
    : null;
  try {
    account = await api.account(id);
    const requestedDay = typeof query.day === "string" ? query.day : undefined;
    // День выбирают и на месячном графике: годится любой из последних 31 дня.
    selectedDay = account.stats?.dailySeries?.some(point => point.day === requestedDay) || withinMonth(requestedDay)
      ? requestedDay : undefined;
    selectedTrend = query.trend === "total" ? "total" : "median";
    // Остальное читается по той же ревизии и одновременно: последовательная
    // цепочка из трёх запросов давала 345 мс вместо 160, а ревизия за это
    // время успевала смениться — она меняется каждые две секунды.
    const revision = account.datasetRevision;
    const [loadedPosts, loadedSiblings] = await Promise.all([
      loadAccountPublications(id, undefined, 100, revision, selectedTrend === "total" ? selectedDay : undefined),
      account.institutionLegacyId !== null
        // Селектор необязателен: страница постов ценна и без него.
        ? api.institutionAccounts(account.institutionLegacyId, "all", 100, undefined, revision).catch(() => null)
        : null,
    ]);
    posts = loadedPosts;
    siblings = loadedSiblings ? [...loadedSiblings.items] : [];
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    reportDetailFailure(`account:${id}`, error);
    return <ApiFailureState retryHref={accountHref(id)} />;
  }
  return <AccountDetail account={account} posts={posts.items} nextCursor={posts.nextCursor ?? null} siblings={siblings} selectedDay={selectedDay} selectedTrend={selectedTrend} anomalyLevels={levels} tailProfile={tail} findings={findings} />;
}

const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/** Московская дата не старше 30 полных дней и не из будущего. */
function withinMonth(day: string | undefined): boolean {
  if (!day || !DAY_PATTERN.test(day)) return false;
  const value = Date.parse(`${day}T00:00:00+03:00`);
  const now = Date.now();
  return Number.isFinite(value) && value <= now && now - value <= 31 * 24 * 3600 * 1000;
}
