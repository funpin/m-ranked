"use client";

import { useMemo } from "react";
import { CurvesChart } from "@/components/compare/compare-charts";
import { institutionRows, type Dashboard, type Network } from "@/lib/compare-dashboard";

const NO_HIGHLIGHTS = new Map<string, string>();

/** Кривые накопления площадки: приезжает вместе с библиотекой графиков. */
export default function LandingCurvesChart({ data, platform }: { data: Dashboard; platform: Network }) {
  const rows = useMemo(() => institutionRows(data, platform), [data, platform]);
  return <CurvesChart data={data} platform={platform} rows={rows} highlights={NO_HIGHLIGHTS} field="views" />;
}
