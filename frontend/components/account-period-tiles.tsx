"use client";

import type { ReactNode } from "react";
import { useState } from "react";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tile, change } from "@/components/account-tile";
import { metricEvidence } from "@/lib/metric-evidence";
import type { components } from "../../contracts/openapi/m-ranked-v1-client";

type AccountStats = components["schemas"]["AccountStats"];
type StatsPeriod = keyof AccountStats["periods"];

const PERIODS: { id: StatsPeriod; label: string; hint: string }[] = [
  { id: "7d", label: "7 д", hint: "Публикации, вышедшие за 7 дней" },
  { id: "30d", label: "30 д", hint: "Публикации, вышедшие за 30 дней" },
  { id: "db", label: "БД", hint: "Все публикации в базе" },
];

const median = (value: number | null) => value === null ? "—" : String(Math.trunc(value));

/** Плитки, которые зависят от периода: число публикаций и медианы. «БД» —
 *  все публикации окна хранения, как было до переключателя; 7 и 30 дней
 *  сужают ту же выборку по дате выхода. Плитки без периода (полная история,
 *  М‑Рейтинг) и значки приходят с сервера готовыми: значки не едут в клиентский
 *  код страницы. */
export function AccountPeriodTiles({ stats, platformLabel, telegram, primary, monitored, rating, icons }: {
  stats: AccountStats; platformLabel: string; telegram: boolean; primary: string;
  monitored: ReactNode; rating: ReactNode;
  icons: { posts: ReactNode; reactions: ReactNode; comments: ReactNode; views: ReactNode };
}) {
  const [period, setPeriod] = useState<StatsPeriod>("db");
  // Ответ API, собранный до появления периодов, приходит без них: тогда
  // показываем «БД» из полей верхнего уровня и не рисуем переключатель.
  const periods = stats.periods as AccountStats["periods"] | undefined;
  const shown = periods?.[period] ?? {
    days: stats.retentionDays, postCount: stats.postCount, medianReactions: stats.medianReactions,
    medianViews: stats.medianViews, medianComments: stats.medianComments, previous: stats.previous,
  };
  const stored = period === "db" || !periods;
  const span = `за ${shown.days} дней`;
  const scope = stored
    ? `Медиана по последним замерам всех публикаций в базе (${span}).`
    : `Медиана по последним замерам публикаций, вышедших ${span}; у самых свежих отклик ещё набирается.`;
  const note = (metric: AccountStats["medianViews"]) => `${scope} ${metricEvidence(metric)}`;
  return <>
    {periods ? <div className="col-span-2 flex items-center justify-between gap-2">
      <span className="text-xs text-muted-foreground">Период публикаций</span>
      <ToggleGroup aria-label="Период публикаций для медиан" spacing={1} value={[period]}
        className="shrink-0 rounded-lg bg-muted/70 p-0.5"
        onValueChange={(next) => {
          // Base UI сообщает пустой выбор, когда нажатую кнопку отжимают.
          const selected = PERIODS.find((option) => option.id === next[0]);
          if (selected) setPeriod(selected.id);
        }}>
        {PERIODS.map((option) => <ToggleGroupItem key={option.id} value={option.id}
          title={option.hint}
          className="px-2.5 aria-pressed:bg-background aria-pressed:text-foreground aria-pressed:shadow-sm">{option.label}</ToggleGroupItem>)}
      </ToggleGroup>
    </div> : null}
    <Tile value={String(shown.postCount)} label={stored ? "публикаций в базе" : `публикаций за ${shown.days} дней`} icon={icons.posts}
      note={`Публикации ${platformLabel}${stored ? " в базе" : ""} за последние ${shown.days} дней.${telegram ? "" : " Метрики, которые площадка не отдаёт, показаны прочерком."}`}
      delta={change(shown.postCount, shown.previous.postCount)} deltaLabel="публикаций за сутки" />
    {monitored}
    <Tile value={median(shown.medianReactions.value)} label={`медиана ${primary}`} icon={icons.reactions}
      note={note(shown.medianReactions)}
      delta={change(shown.medianReactions.value, shown.previous.medianReactions)} />
    <Tile value={median(shown.medianComments.value)} label="медиана комментариев" icon={icons.comments}
      note={note(shown.medianComments)}
      delta={change(shown.medianComments.value, shown.previous.medianComments)} />
    <Tile value={median(shown.medianViews.value)} label="медиана просмотров" icon={icons.views}
      note={note(shown.medianViews)}
      delta={change(shown.medianViews.value, shown.previous.medianViews)} />
    {rating}
  </>;
}
