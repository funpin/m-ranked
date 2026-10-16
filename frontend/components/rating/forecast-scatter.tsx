"use client";

import { CartesianGrid, ReferenceLine, Scatter, ScatterChart, XAxis, YAxis, ZAxis } from "recharts";
import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";

const config = { place: { label: "Вуз", color: "var(--chart-1)" } } satisfies ChartConfig;

type Point = { name: string; predicted: number; actual: number };

function PointTooltip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  const point = active ? payload?.[0]?.payload : undefined;
  if (!point) return null;
  return <div className="bg-background rounded-md border px-2.5 py-1.5 text-xs shadow-sm">
    <p className="font-medium">{point.name}</p>
    <p className="text-muted-foreground tabular-nums">прогноз {point.predicted}, факт {point.actual}</p>
  </div>;
}

/** Прогнозное место против фактического. Первое место — в левом верхнем углу,
 *  точный прогноз ложится на диагональ; ниже диагонали — вуз оказался ниже прогноза. */
export function ForecastScatter({ points, total }: { points: Point[]; total: number }) {
  const limit = Math.min(total, Math.max(20, ...points.map((point) => Math.max(point.predicted, point.actual))) + 5);
  return <figure data-testid="rating-scatter" className="mt-8 max-w-[440px]">
    <figcaption className="mb-2 text-sm font-medium">Прогноз против факта</figcaption>
    <ChartContainer config={config} className="aspect-square w-full">
      <ScatterChart margin={{ top: 8, right: 12, bottom: 28, left: 4 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis type="number" dataKey="predicted" name="Прогноз" domain={[1, limit]} allowDecimals={false} tickLine={false}
          label={{ value: "прогноз места", position: "insideBottom", offset: -16, className: "fill-muted-foreground text-xs" }} />
        <YAxis type="number" dataKey="actual" name="Факт" domain={[1, limit]} allowDecimals={false} reversed tickLine={false} width={36}
          label={{ value: "факт", angle: -90, position: "insideLeft", className: "fill-muted-foreground text-xs" }} />
        <ReferenceLine segment={[{ x: 1, y: 1 }, { x: limit, y: limit }]} stroke="var(--muted-foreground)" strokeOpacity={0.6} strokeDasharray="4 4" ifOverflow="hidden" />
        {/* Метка ≥ 8 px: площадь символа 100 → диаметр около 11 px. */}
        <ZAxis range={[100, 100]} />
        <ChartTooltip cursor={false} content={<PointTooltip />} />
        <Scatter data={points} fill="var(--color-place)" stroke="var(--background)" strokeWidth={2} shape="circle" />
      </ScatterChart>
    </ChartContainer>
    <p className="text-muted-foreground mt-1 text-xs">Точка — вуз. На пунктире — точный прогноз; ниже пунктира вуз оказался ниже прогноза.</p>
  </figure>;
}
