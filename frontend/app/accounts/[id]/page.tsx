import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountDetail } from "@/components/account-detail";
import { ApiFailureState } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { loadAccountPublications, reportDetailFailure } from "@/lib/detail-data";
import { accountHref, UUID_PATTERN } from "@/lib/entity-routes";
import { PLATFORM_LONG_LABELS } from "@/lib/format";
import type { AccountView } from "@/lib/types";

export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }> };

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

export default async function AccountPage({ params }: Props) {
  const { id } = await params;
  if (!UUID_PATTERN.test(id)) notFound();
  let account;
  let posts;
  let siblings: AccountView[] = [];
  try {
    account = await api.account(id);
    // Остальное читается по той же ревизии и одновременно: последовательная
    // цепочка из трёх запросов давала 345 мс вместо 160, а ревизия за это
    // время успевала смениться — она меняется каждые две секунды.
    const revision = account.datasetRevision;
    const [loadedPosts, loadedSiblings] = await Promise.all([
      loadAccountPublications(id, undefined, 100, revision),
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
  return <AccountDetail account={account} posts={posts.items} truncated={Boolean(posts.nextCursor)} siblings={siblings} />;
}
