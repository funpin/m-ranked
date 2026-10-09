"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Clock, Layers, Medal } from "lucide-react";
import { MethodNote } from "@/components/method-note";
import { TimingHeatmap } from "@/components/compare/timing-heatmap";
import {
  formatValue, institutionRows, METRICS, percentileRank, timingGrid, typeRows,
  type Dashboard, type Metric, type Network,
} from "@/lib/compare-dashboard";
import { fetchInstitutionTiming, type InstitutionTiming } from "@/lib/compare-timing";
import { cn } from "@/lib/utils";

type Load<T> = { status: "pending" | "error" } | { status: "ready"; data: T };
const MEASURES: readonly Metric[] = ["views24", "reactions24", "engagement24", "postsPerDay", "subscribers"];
const PLATFORM_IN: Record<Network, string> = { telegram: "в Telegram", vk: "во ВКонтакте", max: "в MAX", rutube: "на Rutube" };

/** Заглушка без пульсации: карточка может долго ждать, пока до неё долистают,
 *  и бесконечная анимация там ни к чему. */
function Placeholder({ className }: { className: string }) {
  return <div className={cn("bg-muted/60 rounded-md", className)} aria-hidden="true" />;
}

/** Грузит, только когда карточка подъезжает к экрану: лента сравнения стоит
 *  последней, и большинство открывших страницу до неё не листает. */
function useNearScreen() {
  const ref = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (!element || near) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) setNear(true);
    }, { rootMargin: "0px 600px 200px 600px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, [near]);
  return [ref, near] as const;
}

function useJson<T>(enabled: boolean, load: () => Promise<T>, key: string): Load<T> {
  const [state, setState] = useState<Load<T>>({ status: "pending" });
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    load().then((data) => alive && setState({ status: "ready", data }), () => alive && setState({ status: "error" }));
    return () => { alive = false; };
    // load меняется вместе с key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, key]);
  return state;
}

function Frame({ icon: Icon, title, note, children, testId }: {
  icon: typeof Clock; title: string; note: string; children: React.ReactNode; testId: string;
}) {
  return (
    <section className="bg-card flex h-full min-w-0 flex-col gap-3 rounded-xl border p-4 text-sm" data-testid={testId}>
      <div className="flex items-start gap-2">
        <Icon className="text-muted-foreground mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <h2 className="font-heading min-w-0 flex-1 text-sm font-semibold">{title}</h2>
        <MethodNote title={title}>{note}</MethodNote>
      </div>
      {children}
    </section>
  );
}

/** Место аккаунта среди вузов своей площадки по мерам «Сравнения» за 30 дней. */
export function AccountStanding({ institutionId, platform }: { institutionId: string; platform: Network }) {
  const [ref, near] = useNearScreen();
  const state = useJson<Dashboard>(near, async () => {
    const response = await fetch("/api/v1/compare/dashboard?period=30d", { headers: { accept: "application/json" } });
    if (!response.ok) throw new Error(String(response.status));
    return response.json() as Promise<Dashboard>;
  }, "dashboard");
  const standing = useMemo(() => {
    if (state.status !== "ready") return null;
    const rows = institutionRows(state.data, platform);
    const row = rows.find((item) => item.id === institutionId);
    if (!row) return { rows: rows.length, items: [] };
    return {
      rows: rows.length,
      items: MEASURES.map((metric) => ({ metric, value: row[metric] as number | null, rank: percentileRank(rows, row, metric) })),
    };
  }, [state, institutionId, platform]);
  return (
    <div ref={ref} className="h-full">
      <Frame icon={Medal} title={`Место среди вузов ${PLATFORM_IN[platform]}`} testId="account-standing"
        note="Меры страницы «Сравнение» за 30 дней. Шкала — процентильный ранг: правее середины — лучше половины вузов площадки. Ранг считается только среди вузов, у которых на площадке есть аккаунт и данные по мере.">
        {standing === null ? (state.status === "error"
          ? <p className="text-muted-foreground text-xs">Не удалось загрузить данные сравнения.</p>
          : <div className="grid gap-3">{MEASURES.map((metric) => <Placeholder key={metric} className="h-8 w-full" />)}</div>)
          : standing.items.length ? (
            <ul className="grid gap-3">
              {standing.items.map(({ metric, value, rank }) => (
                <li key={metric} className="grid gap-1">
                  <div className="flex items-baseline justify-between gap-2 text-xs">
                    <span className="text-muted-foreground">{METRICS[metric].short}</span>
                    <b className="font-heading tabular-nums">{formatValue(value, metric)}</b>
                  </div>
                  <div className="bg-muted relative h-1.5 rounded-full" aria-hidden="true">
                    <span className="bg-muted-foreground/50 absolute top-1/2 left-1/2 h-3 w-px -translate-y-1/2" />
                    {rank !== null ? <span className={cn("absolute inset-y-0 left-0 rounded-full", rank >= 50 ? "bg-chart-2" : "bg-chart-3")}
                      style={{ width: `${Math.max(3, rank)}%` }} /> : null}
                  </div>
                  <p className="text-muted-foreground text-[11px]">
                    {rank === null ? "нет данных за период" : `выше, чем у ${rank} % из ${standing.rows} вузов`}
                  </p>
                </li>
              ))}
            </ul>
          ) : <p className="text-muted-foreground text-xs">У вуза нет данных на этой площадке за 30 дней.</p>}
      </Frame>
    </div>
  );
}

/** Когда аккаунт публикует и какие форматы у него набирают больше. */
export function AccountTiming({ institutionId, platform }: { institutionId: string; platform: Network }) {
  const [ref, near] = useNearScreen();
  const state = useJson<InstitutionTiming>(near, () => fetchInstitutionTiming(institutionId, "30d"), institutionId);
  const ready = state.status === "ready" ? state.data : null;
  const grid = useMemo(() => ready ? timingGrid(ready, platform) : null, [ready, platform]);
  const formats = useMemo(() => ready ? typeRows(ready, platform).slice(0, 4) : [], [ready, platform]);
  const peak = Math.max(1, ...formats.map((row) => row.share));
  return (
    <div ref={ref} className="flex h-full flex-col gap-4">
      <Frame icon={Clock} title="Когда выходят публикации" testId="account-timing"
        note="Публикации аккаунта за 30 дней по дню недели и часу выхода, московское время. Цвет — число публикаций; в подписи ячейки — медиана просмотров за первые сутки.">
        {grid ? <TimingHeatmap grid={grid} />
          : state.status === "error" ? <p className="text-muted-foreground text-xs">Не удалось загрузить время публикаций.</p>
            : <Placeholder className="h-44 w-full" />}
      </Frame>
      <Frame icon={Layers} title="Форматы" testId="account-formats"
        note="Доля публикаций каждого формата за 30 дней и медиана просмотров поста этого формата за первые сутки.">
        {ready ? formats.length ? (
          <ul className="grid gap-2">
            {formats.map((row) => (
              <li key={row.code} className="grid grid-cols-[6.5rem_minmax(0,1fr)_auto] items-center gap-3 text-xs">
                <span className="truncate">{row.type}</span>
                <span className="bg-muted h-1.5 rounded-full" aria-hidden="true">
                  <span className="bg-chart-9 block h-full rounded-full" style={{ width: `${(row.share / peak) * 100}%` }} />
                </span>
                <span className="text-muted-foreground tabular-nums">{Math.round(row.share)} % · {formatValue(row.views24, "views24")}</span>
              </li>
            ))}
          </ul>
        ) : <p className="text-muted-foreground text-xs">Публикаций за 30 дней нет.</p>
          : state.status === "error" ? <p className="text-muted-foreground text-xs">Не удалось загрузить форматы.</p>
            : <Placeholder className="h-20 w-full" />}
      </Frame>
    </div>
  );
}
