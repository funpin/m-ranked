import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { loadAccountPublications } from "@/lib/detail-data";
import { AccountDetail } from "@/components/account-detail";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { legacyPlatformDecision, parsePositiveLegacyId, type SearchParams } from "@/lib/params";

export const dynamic = "force-dynamic";

interface PlatformAccountPageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<SearchParams>;
}

export async function generateMetadata({ params }: PlatformAccountPageProps): Promise<Metadata> {
  const { id } = await params;
  const legacyId = parsePositiveLegacyId(id);
  if (!legacyId) notFound();
  try {
    const account = await api.account(legacyId, "platform_accounts");
    const name = account.title || account.username || account.institutionShortName || account.institutionName;
    const title = `${name}: ${account.platform.toUpperCase()}`;
    const description = `Публикации и статистика аккаунта ${name}.`;
    return {
      title,
      description,
      alternates: { canonical: `/platform-accounts/${legacyId}` },
      openGraph: { title: `${title} — M‑Ranked`, description },
      twitter: { card: "summary", title: `${title} — M‑Ranked`, description },
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return { title: `Аккаунт №${legacyId}` };
  }
}

export default async function PlatformAccountPage({ params, searchParams }: PlatformAccountPageProps) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const legacyId = parsePositiveLegacyId(id);
  if (!legacyId) notFound();

  let account;
  try {
    account = await api.account(legacyId, "platform_accounts");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <>
        <PageHeader title={`Аккаунт №${legacyId}`} description="Не удалось загрузить карточку аккаунта." />
        <ApiFailureState retryHref={`/platform-accounts/${legacyId}`} />
      </>
    );
  }

  if (account.platform === "telegram" && account.channelLegacyId) {
    redirect(`/channels/${account.channelLegacyId}`);
  }
  const platformDecision = legacyPlatformDecision(query.platform, account.platform, true);
  if (platformDecision === "not_found") notFound();
  if (platformDecision === "redirect") redirect(`/platform-accounts/${legacyId}`);
  let posts;
  try {
    posts = await loadAccountPublications(legacyId, "platform_accounts");
    if (posts.datasetRevision !== account.datasetRevision) throw new Error("Revision changed");

  } catch { return <ApiFailureState retryHref={`/platform-accounts/${legacyId}`} />; }
  return <AccountDetail account={account} posts={posts.items} />;
}
