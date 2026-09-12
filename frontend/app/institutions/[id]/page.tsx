import type { Metadata } from "next";
import { notFound } from "next/navigation";
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
  const platform = normalizePlatform(query.platform, "telegram");
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
  const platform = normalizePlatform(query.platform, "telegram");
  const period = normalizePeriod(query.period, "30d");

  try {
    const institution = await api.institution(legacyId, platform, period);
    return <InstitutionDetail institution={institution} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <>
        <PageHeader title={`Вуз №${legacyId}`} description="Не удалось получить согласованную карточку из Spring API." />
        <ApiFailureState retryHref={queryHref(`/institutions/${legacyId}`, { platform, period })} />
      </>
    );
  }
}
