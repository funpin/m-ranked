import type { MetadataRoute } from "next";
import { AI_CRAWLERS } from "@/lib/crawlers";


export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: [...AI_CRAWLERS], disallow: "/" },
      {
        userAgent: "*",
        allow: "/",
        // Служебные адреса и дубли: у страниц с параметрами есть канонический
        // адрес без них, а старые адреса только перенаправляют на новые.
        disallow: ["/manage", "/api/", "/emoji/", "/*?*history_limit=", "/posts/", "/platform-posts/",
          "/channels/", "/platform-accounts/"],
        crawlDelay: 2,
      },
    ],
  };
}
