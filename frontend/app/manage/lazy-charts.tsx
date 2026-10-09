"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";

// recharts приезжает только на вкладки с графиками, а не в первую загрузку панели.
const loading = () => <Skeleton className="h-72 w-full" role="presentation" />;
const cards = (count: number, className: string) => function CardsLoading() {
  return <div className={className} role="presentation">{Array.from({ length: count }, (_, index) => <Skeleton key={index} className="h-48 rounded-lg" />)}</div>;
};
export const LazyVisitorsChart = dynamic(() => import("./charts").then((module) => module.VisitorsChart), { ssr: false, loading });
export const LazySystemCharts = dynamic(() => import("./charts").then((module) => module.SystemCharts), { ssr: false, loading });
export const LazyHostCards = dynamic(() => import("./system-visuals").then((module) => module.HostCards),
  { ssr: false, loading: cards(5, "mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5") });
export const LazyStorageCards = dynamic(() => import("./system-visuals").then((module) => module.StorageCards),
  { ssr: false, loading: cards(3, "mb-5 grid gap-4 md:grid-cols-3") });
export const LazyCollectionChart = dynamic(() => import("./system-visuals").then((module) => module.CollectionChart),
  { ssr: false, loading: () => <Skeleton className="h-44 w-full" role="presentation" /> });
