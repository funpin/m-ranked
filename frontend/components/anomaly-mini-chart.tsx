"use client";
import { Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { axisNumber, legacyDate } from "@/lib/format";
import type { MiniChart } from "@/lib/anomaly";

const COLORS = ["var(--chart-2)", "var(--chart-1)", "var(--chart-4)"];

/** Мини-график признака: одна картинка, которая объясняет формулу. */
export default function AnomalyMiniChart({ chart, label }: { chart: MiniChart; label: string }) {
  if (chart.type === "bars") {
    const config: ChartConfig = { value: { label, color: "var(--chart-2)" } };
    return (
      <div role="img" aria-label={`${label}: ${chart.bars.map((bar) => `${bar.label} ${format(bar.value, chart.percent)}`).join(", ")}`}>
        <ChartContainer config={config} className="h-28 w-full max-w-sm">
          <BarChart data={chart.bars} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
            <XAxis type="number" hide />
            <YAxis type="category" dataKey="label" width={112} tickLine={false} axisLine={false} fontSize={11} />
            <Bar dataKey="value" radius={4} isAnimationActive={false} label={{ position: "right", fontSize: 11, formatter: (value: unknown) => format(Number(value), chart.percent) }}>
              {chart.bars.map((bar) => <Cell key={bar.label} fill={bar.highlight ? "var(--chart-3)" : "var(--muted-foreground)"} fillOpacity={bar.highlight ? 1 : 0.45} />)}
            </Bar>
          </BarChart>
        </ChartContainer>
      </div>
    );
  }
  const config: ChartConfig = Object.fromEntries(chart.series.map((series, index) => [series.key, { label: series.label, color: COLORS[index % COLORS.length] }]));
  const twoAxes = chart.series.some((series) => series.axis === "right");
  return (
    <div role="img" aria-label={`${label}: ${chart.series.map((series) => series.label).join(" и ")} на интервале признака`}>
      <ChartContainer config={config} className="h-36 w-full">
        <ComposedChart data={chart.points} margin={{ left: 0, right: twoAxes ? 0 : 8, top: 6, bottom: 0 }}>
          <CartesianGrid vertical={false} yAxisId="left" stroke="var(--border)" />
          <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} hide />
          <YAxis yAxisId="left" width={48} tickLine={false} axisLine={false} tickFormatter={axisNumber} fontSize={10} />
          {twoAxes ? <YAxis yAxisId="right" orientation="right" width={48} tickLine={false} axisLine={false} tickFormatter={axisNumber} fontSize={10} /> : null}
          <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => {
            const at = (payload?.[0] as { payload?: { t?: number } } | undefined)?.payload?.t;
            return typeof at === "number" ? legacyDate(new Date(at).toISOString()) : "";
          }} />} />
          {chart.band ? <Area yAxisId="left" dataKey={(point: Record<string, number | null>) => point[chart.band!.low] === null ? null : [point[chart.band!.low], point[chart.band!.high]]}
            stroke="none" fill="var(--muted-foreground)" fillOpacity={0.14} isAnimationActive={false} connectNulls={false} name="полоса модели" /> : null}
          {chart.series.map((series, index) => (
            <Line key={series.key} yAxisId={series.axis ?? "left"} dataKey={series.key} dot={false} connectNulls={false}
              stroke={COLORS[index % COLORS.length]} strokeWidth={series.dashed ? 1.5 : 2}
              strokeDasharray={series.dashed ? "5 4" : undefined} isAnimationActive={false} />
          ))}
        </ComposedChart>
      </ChartContainer>
    </div>
  );
}

function format(value: number, percent: boolean) {
  return percent ? `${(value * 100).toFixed(1)} %` : String(Math.round(value));
}
