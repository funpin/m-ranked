import { notFound, permanentRedirect } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { accountHref, publicationHref, withSearch } from "@/lib/entity-routes";
import { legacyPlatformDecision, parsePositiveLegacyId, type SearchParams } from "@/lib/params";
import { ApiFailureState } from "./ui";

export const legacyDetailRoutes = {
  channels: "channels", "platform-accounts": "platform_accounts",
  posts: "posts", "platform-posts": "platform_posts",
} as const;

export async function LegacyDetailRedirect({ id, query, route }: {
  id: string; query: SearchParams; route: keyof typeof legacyDetailRoutes;
}) {
  const legacyId = parsePositiveLegacyId(id);
  if (!legacyId) notFound();
  const type = legacyDetailRoutes[route];
  let destination: string;
  let platform: "telegram" | "vk" | "max" | "rutube";
  try {
    if (type === "channels" || type === "platform_accounts") {
      const account = await api.account(legacyId, type);
      platform = account.platform;
      destination = accountHref(account.accountId);
    } else {
      const publication = await api.publication(legacyId, type);
      platform = publication.platform;
      destination = publicationHref(publication.publicationId);
    }
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return <ApiFailureState retryHref={withSearch(`/${route}/${id}`, query)} />;
  }
  if (legacyPlatformDecision(query.platform, platform, route.startsWith("platform-")) === "not_found") notFound();
  if ((type === "channels" || type === "posts") && platform !== "telegram") notFound();
  permanentRedirect(withSearch(destination, query));
}
