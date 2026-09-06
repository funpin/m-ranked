import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AccountDetail } from "@/components/account-detail";
import { ApiFailureState } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { loadAccountPublications } from "@/lib/detail-data";
import { accountHref, UUID_PATTERN } from "@/lib/entity-routes";
import { PLATFORM_LONG_LABELS } from "@/lib/format";

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
  try {
    account = await api.account(id);
    posts = await loadAccountPublications(id);
    if (posts.datasetRevision !== account.datasetRevision) throw new Error("Revision changed");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return <ApiFailureState retryHref={accountHref(id)} />;
  }
  return <AccountDetail account={account} posts={posts.items} />;
}
