import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { PublicationDetail } from "@/components/publication-detail";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { legacyPlatformDecision, parsePositiveLegacyId, type SearchParams } from "@/lib/params";

export const dynamic = "force-dynamic";

interface PlatformPostPageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<SearchParams>;
}

export async function generateMetadata({ params }: PlatformPostPageProps): Promise<Metadata> {
  const { id } = await params;
  const legacyId = parsePositiveLegacyId(id);
  if (!legacyId) notFound();
  try {
    const publication = await api.publication(legacyId, "platform_posts");
    const title = `Публикация ${publication.platform.toUpperCase()} №${publication.legacyId}`;
    const description = "Последний согласованный замер публикации из публичного Spring API.";
    return {
      title,
      description,
      alternates: { canonical: `/platform-posts/${legacyId}` },
      openGraph: { title: `${title} — M‑Ranked`, description },
      twitter: { card: "summary", title: `${title} — M‑Ranked`, description },
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return { title: `Публикация №${legacyId}`, alternates: { canonical: `/platform-posts/${legacyId}` } };
  }
}

export default async function PlatformPostPage({ params, searchParams }: PlatformPostPageProps) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const legacyId = parsePositiveLegacyId(id);
  if (!legacyId) notFound();

  let publication;
  try {
    publication = await api.publication(legacyId, "platform_posts");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <>
        <PageHeader title={`Публикация №${legacyId}`} description="Не удалось получить последний согласованный замер из Spring API." />
        <ApiFailureState retryHref={`/platform-posts/${legacyId}`} />
      </>
    );
  }
  const platformDecision = legacyPlatformDecision(query.platform, publication.platform, true);
  if (platformDecision === "not_found") notFound();
  if (platformDecision === "redirect") redirect(`/platform-posts/${legacyId}`);
  return <PublicationDetail publication={publication} />;
}
