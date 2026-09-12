import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { AccountDetail } from "@/components/account-detail";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { legacyPlatformDecision, parsePositiveLegacyId, type SearchParams } from "@/lib/params";

export const dynamic = "force-dynamic";

interface ChannelPageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<SearchParams>;
}

export async function generateMetadata({ params, searchParams }: ChannelPageProps): Promise<Metadata> {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const legacyId = parsePositiveLegacyId(id);
  if (!legacyId) notFound();
  try {
    const account = await api.account(legacyId, "channels");
    const name = account.title || (account.username ? `@${account.username}` : account.institutionShortName) || account.institutionName;
    const title = `${name}: Telegram`;
    const description = `Telegram-канал ${account.institutionName} из согласованной проекции Spring API.`;
    return {
      title,
      description,
      openGraph: { title: `${title} — M‑Ranked`, description },
      twitter: { card: "summary", title: `${title} — M‑Ranked`, description },
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return { title: `Канал №${legacyId}` };
  }
}

export default async function ChannelPage({ params, searchParams }: ChannelPageProps) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const legacyId = parsePositiveLegacyId(id);
  if (!legacyId) notFound();

  let account;
  try {
    account = await api.account(legacyId, "channels");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <>
        <PageHeader title={`Канал №${legacyId}`} description="Не удалось получить карточку Telegram-канала из Spring API." />
        <ApiFailureState retryHref={`/channels/${legacyId}`} />
      </>
    );
  }
  const platformDecision = legacyPlatformDecision(query.platform, account.platform);
  if (platformDecision === "not_found" || account.platform !== "telegram") notFound();
  if (platformDecision === "redirect") redirect(`/channels/${legacyId}`);
  return <AccountDetail account={account} channelCompatibility />;
}
