import type { MetadataRoute } from "next";
import { AI_CRAWLERS } from "@/lib/crawlers";
import { publicOrigin } from "@/lib/deployment";


export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: [...AI_CRAWLERS], disallow: "/" },
      {
        userAgent: "*",
        allow: "/",
        // Служебные адреса и дубли: у страниц с параметрами есть канонический
        // адрес без них, а старые адреса только перенаправляют на новые.
        // Открыты только выбор площадки и периода на списках; страницы поста,
        // аккаунта и вуза — лишь канонические (карта сайта перечисляет их).
        disallow: ["/manage", "/api/", "/emoji/", "/posts/", "/platform-posts/", "/channels/", "/platform-accounts/",
          "/publications/*?", "/accounts/*?", "/institutions/*?",
          ...["history_limit", "sort", "direction", "q", "cursor", "day", "trend", "highlight", "limit", "view", "nocache"]
            .map((name) => `/*?*${name}=`)],
        crawlDelay: 2,
      },
    ],
    sitemap: new URL("/sitemap.xml", publicOrigin()).href,
  };
}
