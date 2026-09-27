"use client";

import dynamic from "next/dynamic";
import { useMemo, useRef, useState, type ReactNode } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { PlatformLogo } from "@/components/platform-logo";
import type { Dashboard, Network } from "@/lib/compare-dashboard";
import { KNOWN_PLATFORMS } from "@/lib/landing";
import { cn } from "@/lib/utils";
import { Ribbon } from "./ribbon";
import { useNear } from "./use-near";

// Те же графики, что на странице сравнения. Библиотека графиков не входит в
// первую загрузку главной: фрагмент запрашивается, когда блок подъезжает к экрану.
const ReachAreaChart = dynamic(() => import("@/components/compare/compare-charts").then((module) => module.ReachAreaChart), {
  ssr: false, loading: () => <ChartSkeleton height={300} />,
});
const HourlyReachChart = dynamic(() => import("@/components/compare/compare-charts").then((module) => module.HourlyReachChart), {
  ssr: false, loading: () => <ChartSkeleton height={280} />,
});
const LevelsByPlatform = dynamic(() => import("@/components/compare/compare-charts").then((module) => module.LevelsByPlatform), {
  ssr: false, loading: () => <ChartSkeleton height={240} />,
});
const TimingHeatmap = dynamic(() => import("@/components/compare/timing-heatmap").then((module) => module.TimingHeatmap), {
  ssr: false, loading: () => <ChartSkeleton height={240} />,
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

/** Последние 30 дней на всех площадках: просмотры по дням выхода. */
export function LandingReach({ data }: { data: Dashboard }) {
  return (
    <div data-testid="landing-reach">
      <WhenNear height={300}><ReachAreaChart data={data} platform="all" /></WhenNear>
    </div>
  );
}

type RhythmPlatform = "all" | Network;

/** Плитка ленты: график в тёмной карточке и подпись под ней — как в галереях
 *  Apple: жирное начало и серое продолжение. */
function RhythmTile({ title, text, height, children }: { title: string; text: string; height: number; children: ReactNode }) {
  return (
    <figure className="landing-ribbon-item landing-slide grid w-[min(86vw,760px)] shrink-0 snap-start content-start gap-5">
      <div className="landing-tile grid min-h-[360px] content-center p-5 sm:p-8">
        <WhenNear height={height}>{children}</WhenNear>
      </div>
      <figcaption className="text-muted-foreground max-w-xl px-1 text-base leading-relaxed text-pretty">
        <b className="text-foreground font-semibold">{title}</b> {text}
      </figcaption>
    </figure>
  );
}

/** Ритм площадок: лента из трёх графиков — час выхода, дни недели, итоги
 *  анализа. Площадку выбирает переключатель над лентой. */
export function LandingRhythm({ data }: { data: Dashboard }) {
  const available = useMemo(() => NETWORKS.filter((network) => data.timing.some((cell) => cell.platform === network && cell.posts > 0)), [data]);
  const [platform, setPlatform] = useState<RhythmPlatform>("all");
  return (
    <div className="grid gap-8" data-testid="landing-rhythm">
      <div className="flex justify-center">
        <Switcher label="Площадка" value={platform} onChange={setPlatform}
          options={[{ value: "all" as const, label: "Все" }, ...available.map((network) => ({
            value: network,
            label: <><PlatformLogo platform={network} size={16} decorative /><span className="max-sm:sr-only">{KNOWN_PLATFORMS[network].name}</span></>,
          }))]} />
      </div>
      <Ribbon label="Ритм площадок">
        <RhythmTile title="Час выхода." height={280}
          text="Столбцы — сколько публикаций выходит в каждый час, линия — сколько типичный пост этого часа набирает за первые сутки.">
          <HourlyReachChart data={data} platform={platform} />
        </RhythmTile>
        <RhythmTile title="Дни недели." height={260} text="Когда вузы публикуют чаще всего: день недели и час выхода.">
          <TimingHeatmap data={data} platform={platform} />
        </RhythmTile>
        <RhythmTile title="Итоги анализа." height={240} text="Какая доля постов каждой площадки оказалась на каждом уровне анализа динамики.">
          <LevelsByPlatform data={data} />
        </RhythmTile>
      </Ribbon>
    </div>
  );
}
