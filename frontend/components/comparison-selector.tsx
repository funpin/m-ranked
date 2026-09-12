"use client";

import { useState, type ReactNode } from "react";

export interface ComparisonCandidate { id: number; label: string; description: string }

export function ComparisonSelector({ candidates, selected, type, children, query = "", platformLabel = "Telegram" }: {
  candidates: ComparisonCandidate[];
  selected: number[];
  type: "channels" | "institutions";
  children: ReactNode;
  query?: string;
  platformLabel?: string;
}) {
  const [ids, setIds] = useState(() => new Set(selected));
  const [search, setSearch] = useState(query);
  const normalized = search.trim().toLocaleLowerCase("ru");
  return <>
    <div className="compare-filter-head"><div><h2>Настройка сравнения</h2><p className="panel-note">{type === "channels" ? "Выберите каналы и глубину истории публикаций." : `Выберите вузы и глубину истории публикаций ${platformLabel}.`}</p></div><output className="selection-count pill" aria-live="polite">Выбрано: {ids.size} из {candidates.length}</output></div>
    <div className="selector-toolbar">
      <input type="search" aria-label={type === "channels" ? "Поиск канала" : "Поиск вуза"} value={search} onChange={(event) => setSearch(event.target.value)} placeholder={type === "channels" ? "Найти вуз или @канал" : `Найти вуз или аккаунт ${platformLabel}`} autoComplete="off" />
      <button className="secondary" type="button" onClick={() => setIds(new Set(candidates.map((item) => item.id)))}>Выбрать все</button>
      <button className="secondary" type="button" onClick={() => setIds(new Set())}>Снять выбор</button>
    </div>
    <p className="panel-note compare-selection-note">{type === "channels" ? "Для читаемого графика обычно достаточно выбрать 2–5 каналов. Линии также можно скрывать прямо в легенде." : "Для читаемого графика обычно достаточно 2–5 вузов. Несколько аккаунтов одной площадки у вуза объединяются."}</p>
    <div className="choice-grid">
      {candidates.map((item) => <label className="choice" key={item.id} hidden={!`${item.label} ${item.description}`.toLocaleLowerCase("ru").includes(normalized)}>
        <input type="checkbox" name={type} value={item.id} checked={ids.has(item.id)} onChange={(event) => setIds((previous) => {
          const next = new Set(previous);
          if (event.target.checked) next.add(item.id); else next.delete(item.id);
          return next;
        })} />
        <span><span className="choice-main">{item.label}</span><span className="choice-meta">{item.description}</span></span>
      </label>)}
    </div>
    {children}
  </>;
}
