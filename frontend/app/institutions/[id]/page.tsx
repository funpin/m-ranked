import { accountHref } from "@/lib/entity-routes";
import type { Metadata } from "next";
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
  let accountsTruncated = false;
  try {
    const accountPage = await api.institutionAccounts(legacyId,platform,100);
    accounts = accountPage.items;
    accountsTruncated = Boolean(accountPage.nextCursor);
    // Legacy platform cards use SQLite's binary ORDER BY platform, title, username.
    if(platform !== "telegram") {
      const textOrder=(a:string|null,b:string|null)=>a===b?0:a===null?-1:b===null?1:a<b?-1:1;
      accounts.sort((a,b)=>textOrder(a.platform,b.platform)||textOrder(a.title,b.title)||textOrder(a.username,b.username));
    }
    if (accountPage.datasetRevision !== institution.datasetRevision) throw new Error("Revision changed");
  } catch { return <ApiFailureState retryHref={queryHref(`/institutions/${legacyId}`,{platform})} />; }
  if(platform !== "all" && accounts.length === 1) {
    const account=accounts[0]!;
    redirect(accountHref(account.accountId));
  }
  // The institution endpoint intentionally performs a fixed two-request read.
  // Per-account details and publications stay on the account pages instead of
  // creating a production-size 2N fan-out from one web request.
  return <InstitutionDetail institution={institution} accounts={accounts} posts={[]} accountsTruncated={accountsTruncated} />;
}
