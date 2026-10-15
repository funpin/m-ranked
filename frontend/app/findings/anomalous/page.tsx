import type { Metadata } from "next";
import { AnomalousResults } from "@/components/findings/anomalous-results";
import { FindingsScreen } from "@/components/findings/findings-screen";
import type { SearchParams } from "@/lib/params";
import type { AnomalousFindingsPage } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Находки: аномальные посты",
  description: "Посты вузов с самой необычной динамикой счётчиков: уровень аномалии и доля необычного прироста.",
};

export default async function AnomalousFindingsRoute({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return <FindingsScreen raw={await searchParams} view="anomalous" results={(page, query, key) =>
    <AnomalousResults key={key} page={page as AnomalousFindingsPage} query={query} />} />;
}
