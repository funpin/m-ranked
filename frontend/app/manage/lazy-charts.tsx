"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";

// recharts приезжает только на вкладки с графиками, а не в первую загрузку панели.
const loading = () => <Skeleton className="h-72 w-full" role="presentation" />;
export const LazyVisitorsChart = dynamic(() => import("./charts").then((module) => module.VisitorsChart), { ssr: false, loading });
export const LazySystemCharts = dynamic(() => import("./charts").then((module) => module.SystemCharts), { ssr: false, loading });
