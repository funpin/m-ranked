import type { Metadata } from "next";
import Link from "@/components/native-link";

export const metadata: Metadata = {
  title: "m-ranked — соцсети вузов как есть",
  description: "Мониторинг и сравнительная аналитика официальных соцсетей российских вузов.",
};

/** Временная главная: собирается на следующем этапе. */
export default function HomePage() {
  return (
    <section className="grid gap-6 py-24">
      <h1 className="font-heading text-5xl font-bold tracking-tight">Соцсети вузов. Как есть.</h1>
      <Link className="text-chart-2 underline" href="/rating" prefetch={false}>Открыть рейтинг</Link>
    </section>
  );
}
