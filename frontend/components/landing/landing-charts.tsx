"use client";

import dynamic from "next/dynamic";
import { useMemo, useRef, useState, type ReactNode } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { PlatformLogo } from "@/components/platform-logo";
import type { Dashboard, Network } from "@/lib/compare-dashboard";
import { KNOWN_PLATFORMS } from "@/lib/landing";
import { cn } from "@/lib/utils";
import { useNear } from "./use-near";

// Те же графики, что на странице сравнения. Библиотека графиков не входит в
// первую загрузку главной: фрагмент запрашивается, когда блок подъезжает к экрану.
const ReachAreaChart = dynamic(() => import("@/components/compare/compare-charts").then((module) => module.ReachAreaChart), {
  ssr: false, loading: () => <ChartSkeleton height={300} />,
});
const DailyChart = dynamic(() => import("@/components/compare/compare-charts").then((module) => module.DailyChart), {
  ssr: false, loading: () => <ChartSkeleton height={300} />,
});
const CurvesChart = dynamic(() => import("./landing-curves-chart"), {
  ssr: false, loading: () => <ChartSkeleton height={340} />,
});

const NETWORKS = ["telegram", "vk", "max", "rutube"] as const satisfies readonly Network[];

function ChartSkeleton({ height }: { height: number }) {
  return <Skeleton className="w-full rounded-lg" style={{ height }} aria-label="График загружается" role="status" />;
}

/** Рисует график, только когда место под него рядом с экраном. */
function WhenNear({ height, children }: { height: number; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const near = useNear(box);
  return <div ref={box} style={{ minHeight: height }}>{near ? children : <ChartSkeleton height={height} />}</div>;
}

/** Переключатель-«таблетка»: выбранный пункт поднимается карточкой. */
function Switcher<T extends string>({ value, options, onChange, label }: {
  value: T; options: readonly { value: T; label: ReactNode }[]; onChange: (value: T) => void; label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="bg-muted/60 ring-foreground/5 inline-flex flex-wrap justify-self-start gap-0.5 rounded-full p-1 ring-1">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button key={option.value} type="button" role="radio" aria-checked={active} onClick={() => onChange(option.value)}
            className={cn("inline-flex min-h-8 items-center gap-1.5 rounded-full px-3 text-xs font-medium ring-1 transition-[background-color,color,box-shadow] duration-300",
              "focus-visible:ring-ring/60 outline-none focus-visible:ring-2",
              active ? "bg-background text-foreground ring-foreground/10 shadow-sm" : "text-muted-foreground hover:text-foreground ring-transparent")}>
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

type ReachView = "views" | "posts";

/** Последние 30 дней на всех площадках: просмотры или публикации по дням. */
export function LandingReach({ data }: { data: Dashboard }) {
  const [view, setView] = useState<ReachView>("views");
  return (
    <div className="grid gap-4" data-testid="landing-reach">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-muted-foreground text-sm">Последние 30 дней, все площадки. Живые данные — те же, что в сравнении.</p>
        <Switcher label="Что показать" value={view} onChange={setView}
          options={[{ value: "views", label: "Просмотры" }, { value: "posts", label: "Публикации" }]} />
      </div>
      <WhenNear height={300}>
        {view === "views" ? <ReachAreaChart data={data} platform="all" /> : <DailyChart data={data} platform="all" />}
      </WhenNear>
    </div>
  );
}

/** Типичный пост площадки по часам жизни: медиана и тонкие линии всех вузов. */
export function LandingCurves({ data }: { data: Dashboard }) {
  const available = useMemo(() => NETWORKS.filter((network) =>
    data.curves.some((curve) => curve.platform === network && curve.views.some((value) => value !== null))), [data]);
  const [platform, setPlatform] = useState<Network>(available[0] ?? "telegram");
  if (!available.length) return null;
  return (
    <div className="grid gap-4" data-testid="landing-curves">
      <Switcher label="Площадка" value={platform} onChange={setPlatform}
        options={available.map((network) => ({
          value: network,
          label: <><PlatformLogo platform={network} size={16} decorative />{KNOWN_PLATFORMS[network].name}</>,
        }))} />
      <WhenNear height={340}>
        <CurvesChart data={data} platform={platform} />
      </WhenNear>
    </div>
  );
}
