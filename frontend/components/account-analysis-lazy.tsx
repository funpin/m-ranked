"use client";

import dynamic from "next/dynamic";
import type { ComponentProps } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import type { AccountAnalysisCard as Card } from "@/components/account-analysis-card";

// Блок анализа аккаунта стоит ниже показателей и раскрывается по нажатию, а
// вместе с раскрывашкой Base UI весит около 30 КиБ: в первую загрузку страницы
// аккаунта (бюджет 205 КиБ) он не идёт и приезжает отдельным куском.
const AccountAnalysisCard = dynamic(
  () => import("@/components/account-analysis-card").then((module) => module.AccountAnalysisCard),
  { ssr: false, loading: () => <Skeleton className="mt-5 h-12 w-full rounded-xl" role="status" aria-label="Анализ аккаунта загружается" /> },
);

export function AccountAnalysis(props: ComponentProps<typeof Card>) {
  return <AccountAnalysisCard {...props} />;
}
