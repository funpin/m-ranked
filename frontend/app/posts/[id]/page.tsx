import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { PublicationDetail } from "@/components/publication-detail";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import {
  legacyPlatformDecision,
  normalizeHistoryLimit,
  parsePositiveLegacyId,
  queryHref,
  type SearchParams,
} from "@/lib/params";

export const dynamic = "force-dynamic";

interface PostPageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<SearchParams>;
}

export async function generateMetadata({ params, searchParams }: PostPageProps): Promise<Metadata> {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const legacyId = parsePositiveLegacyId(id);
  if (!legacyId) notFound();
  if (legacyPlatformDecision(query.platform, "telegram") === "not_found") notFound();
  try {
    const publication = await api.publication(legacyId, "posts");
    const title = `Telegram-публикация №${publication.legacyId}`;
    const description = `Последний согласованный замер публикации от ${formatMetadataDate(publication.publishedAt)}.`;
    return {
      title,
      description,
      alternates: { canonical: `/posts/${legacyId}` },
      openGraph: { title: `${title} — M‑Ranked`, description },
      twitter: { card: "summary", title: `${title} — M‑Ranked`, description },
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return { title: `Публикация №${legacyId}`, alternates: { canonical: `/posts/${legacyId}` } };
  }
}

function formatMetadataDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "неизвестной даты" : new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit", year: "numeric",
  }).format(date);
}

export default async function PostPage({ params, searchParams }: PostPageProps) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const legacyId = parsePositiveLegacyId(id);
  if (!legacyId) notFound();
  const platformDecision = legacyPlatformDecision(query.platform, "telegram");
  if (platformDecision === "not_found") notFound();
  if (platformDecision === "redirect") redirect(`/posts/${legacyId}`);
  const historyLimit = normalizeHistoryLimit(query.history_limit);

  try {
    const publication = await api.publication(legacyId, "posts");
    return <PublicationDetail publication={publication} historyLimit={historyLimit} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <>
        <PageHeader title={`Публикация №${legacyId}`} description="Не удалось получить последний согласованный замер из Spring API." />
        <ApiFailureState retryHref={queryHref(`/posts/${legacyId}`, { history_limit: historyLimit })} />
      </>
    );
  }
}
