import { LegacyDetailRedirect } from "@/components/legacy-detail-redirect";
import type { SearchParams } from "@/lib/params";

export const dynamic = "force-dynamic";
export default async function LegacyPage({ params, searchParams }: {
  params: Promise<{ id: string }>; searchParams: Promise<SearchParams>;
}) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  return <LegacyDetailRedirect id={id} query={query} route="channels" />;
}
