import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PublicationDetail } from "@/components/publication-detail";
import { ApiFailureState } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { loadPublicationHistory } from "@/lib/detail-data";
import { publicationHref, UUID_PATTERN } from "@/lib/entity-routes";
import { PLATFORM_LONG_LABELS } from "@/lib/format";
import { normalizeHistoryLimit, queryHref, type SearchParams } from "@/lib/params";

export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }>; searchParams: Promise<SearchParams> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  if (!UUID_PATTERN.test(id)) notFound();
  try {
    const publication = await api.publication(id);
    return { title: `Публикация ${PLATFORM_LONG_LABELS[publication.platform]} №${publication.displayExternalId ?? publication.externalId ?? publication.legacyId}`,
      description: "История просмотров, реакций и других показателей публикации.",
      alternates: { canonical: publicationHref(publication.publicationId) } };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return { title: "Публикация", alternates: { canonical: publicationHref(id) } };
  }
}

export default async function PublicationPage({ params, searchParams }: Props) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  if (!UUID_PATTERN.test(id)) notFound();
  const historyLimit = normalizeHistoryLimit(query.history_limit);
  let history;
  try {
    history = await loadPublicationHistory(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return <ApiFailureState retryHref={queryHref(publicationHref(id), { history_limit: historyLimit })} />;
  }
  return <PublicationDetail history={history} historyLimit={historyLimit} />;
}
