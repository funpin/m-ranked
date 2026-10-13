import type { Metadata } from "next";
import { FindingsResults } from "@/components/findings/findings-results";
import { FindingsScreen } from "@/components/findings/findings-screen";
import type { SearchParams } from "@/lib/params";
import type { FindingsPage } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Находки: выше нормы",
  description: "Посты вузов, сработавшие лучше обычного для своего аккаунта: индекс к норме на одном возрасте поста.",
};

export default async function FindingsPageRoute({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return <FindingsScreen raw={await searchParams} view="above_norm" results={(page, query, key, anomaliesVisible) =>
    <FindingsResults key={key} page={page as FindingsPage} query={query} anomaliesVisible={anomaliesVisible} />} />;
}
