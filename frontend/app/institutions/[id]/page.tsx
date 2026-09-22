import { notFound, redirect } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { accountHref } from "@/lib/entity-routes";
import { normalizePlatform, parsePositiveLegacyId, type SearchParams } from "@/lib/params";

export const dynamic = "force-dynamic";

interface InstitutionPageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<SearchParams>;
}

export default async function InstitutionPage({ params, searchParams }: InstitutionPageProps) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const legacyId = parsePositiveLegacyId(id);
  if (!legacyId) notFound();
  const platform = normalizePlatform(query.platform, "all");

  let accounts;
  try {
    const accountPage = await api.institutionAccounts(legacyId,platform,100);
    const priority = { telegram: 0, vk: 1, max: 2, rutube: 3 } as const;
    accounts = [...accountPage.items].sort((left, right) =>
      priority[left.platform] - priority[right.platform]
      || left.accountId.localeCompare(right.accountId));
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  const account = accounts[0];
  if (!account) notFound();
  redirect(accountHref(account.accountId));
}
