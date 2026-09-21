import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "m-ranked — аналитика соцсетей вузов",
    short_name: "m-ranked",
    description: "Сравнение активности, охвата и качества данных официальных соцсетей российских вузов.",
    id: "/",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "any",
    background_color: "#0d1117",
    theme_color: "#0d1117",
    icons: [
      {
        src: "/icons/app-icon-192.png?v=20260921",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/app-icon-512.png?v=20260921",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/app-icon-512.png?v=20260921",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
