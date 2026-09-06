import type { Metadata } from "next";
import { collectPages, uniqueRows } from "@/lib/continuation";
import { loadAccountPublications } from "@/lib/detail-data";
import { notFound, redirect } from "next/navigation";
import { InstitutionDetail } from "@/components/institution-detail";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { normalizePeriod, normalizePlatform, parsePositiveLegacyId, queryHref, type SearchParams } from "@/lib/params";

export const dynamic = "force-dynamic";

interface InstitutionPageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<SearchParams>;
}

export async function generateMetadata({ params, searchParams }: InstitutionPageProps): Promise<Metadata> {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const legacyId = parsePositiveLegacyId(id);
  if (!legacyId) notFound();
  const platform = normalizePlatform(query.platform, "all");
  const period = normalizePeriod(query.period, "30d");
  try {
    const institution = await api.institution(legacyId, platform, period);
    const name = institution.shortName || institution.canonicalName;
    const description = `Показатели активности ${institution.canonicalName} с прозрачной выборкой и качеством данных.`;
    return {
      title: name,
      description,
      openGraph: { title: `${name} — M‑Ranked`, description },
      twitter: { card: "summary", title: `${name} — M‑Ranked`, description },
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return { title: `Вуз №${legacyId}` };
  }
}

export default async function InstitutionPage({ params, searchParams }: InstitutionPageProps) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const legacyId = parsePositiveLegacyId(id);
  if (!legacyId) notFound();
  const platform = normalizePlatform(query.platform, "all");
  const period = normalizePeriod(query.period, "30d");

  let institution;
  try {
    institution = await api.institution(legacyId, platform, period);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <>
        <PageHeader title={`Вуз №${legacyId}`} description="Не удалось загрузить карточку вуза." />
        <ApiFailureState retryHref={queryHref(`/institutions/${legacyId}`, { platform, period })} />
      </>
    );
  }
  let accounts;
  try {
    const pages = await collectPages((cursor) => api.institutionAccounts(legacyId,platform,cursor),(page) => page.nextCursor);
    accounts = uniqueRows(pages.flatMap((page) => page.items),(account) => account.accountId);
    // Legacy platform cards use SQLite's binary ORDER BY platform, title, username.
    if(platform !== "telegram") {
      const textOrder=(a:string|null,b:string|null)=>a===b?0:a===null?-1:b===null?1:a<b?-1:1;
      accounts.sort((a,b)=>textOrder(a.platform,b.platform)||textOrder(a.title,b.title)||textOrder(a.username,b.username));
    }
    if (pages[0]!.datasetRevision !== institution.datasetRevision) throw new Error("Revision changed");
  } catch { return <ApiFailureState retryHref={queryHref(`/institutions/${legacyId}`,{platform})} />; }
  if(platform !== "all" && accounts.length === 1) {
    const account=accounts[0]!;
    redirect(account.platform === "telegram" && account.channelLegacyId ? `/channels/${account.channelLegacyId}` : `/platform-accounts/${account.platformAccountLegacyId ?? account.legacyId}`);
  }
  const posts = [];
  try {
    for(const [index,account] of accounts.entries()) {
      const id=platform === "telegram" ? account.channelLegacyId ?? account.legacyId : account.platformAccountLegacyId ?? account.legacyId;
      const type=platform === "telegram" ? "channels" : "platform_accounts";
      const enriched=await api.account(id,type);
      if(enriched.datasetRevision!==institution.datasetRevision) throw new Error("Revision changed");
      accounts[index]={...account,stats:enriched.stats};
      const page=await loadAccountPublications(id,type);
      if(page.datasetRevision !== institution.datasetRevision) throw new Error("Revision changed");
      posts.push(...page.items.map((post) => ({...post,account})));
    }
    posts.sort((a,b) => Date.parse(b.publishedAt)-Date.parse(a.publishedAt) || (b.legacyId ?? 0)-(a.legacyId ?? 0));
  } catch { return <ApiFailureState retryHref={queryHref(`/institutions/${legacyId}`,{platform})} />; }
  return <InstitutionDetail institution={institution} accounts={accounts} posts={[...new Map(posts.map((post) => [post.publicationId,post])).values()].slice(0,500)} />;
}
