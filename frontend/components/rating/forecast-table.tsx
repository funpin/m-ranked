import Link from "@/components/native-link";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { hasActual, rankDelta, rankLabel, rowsFor, sourceNote, stripPosition } from "@/lib/rating";
import type { RatingCategory, RatingForecast, RatingForecastCell } from "@/lib/types";
import { cn } from "@/lib/utils";

const PLATFORM_COLUMNS = [["max", "MAX"], ["vk", "VK"], ["rutube", "Rutube"]] as const;

function Delta({ value }: { value: number | null }) {
  if (value === null || value === 0) return <span className="text-muted-foreground">—</span>;
  const label = value > 0 ? `выше на ${value}` : `ниже на ${-value}`;
  return <span aria-label={label} className={value > 0 ? "text-success" : "text-destructive"}>
    {value > 0 ? `↑${value}` : `↓${-value}`}
  </span>;
}

/** Место на шкале всех вузов рейтинга: полоса — диапазон при типичной ошибке,
 *  точка — прогноз, кольцо — факт опубликованного месяца. Числа стоят рядом
 *  текстом, поэтому полоса скрыта от читалок экрана. */
function PlaceStrip({ cell, total }: { cell: RatingForecastCell; total: number }) {
  const from = stripPosition(cell.rankBest, total);
  const to = stripPosition(cell.rankWorst, total);
  return <span aria-hidden="true" className="bg-muted relative block h-1.5 w-full min-w-24 rounded-full">
    <span className="bg-chart-1/30 absolute inset-y-0 rounded-full" style={{ left: `${from}%`, width: `${Math.max(to - from, 1.5)}%` }} />
    <span className="bg-chart-1 ring-background absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2"
      style={{ left: `${stripPosition(cell.rank, total)}%` }} />
    {cell.actualRank !== null ? <span className="border-foreground ring-background absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 ring-1"
      style={{ left: `${stripPosition(cell.actualRank, total)}%` }} /> : null}
  </span>;
}

export function ForecastTable({ forecast, category, total }: { forecast: RatingForecast; category: RatingCategory; total: number }) {
  const actual = hasActual(forecast);
  // Сводное место прошлого месяца — справка, не прогноз; есть с первого импорта после выкатки.
  const consolidated = category === "social" && forecast.rows.some((row) => row.baseConsolidatedRank !== null);
  return <Table className="tabular-nums">
    <TableCaption className="sr-only">Прогноз мест: {forecast.period}</TableCaption>
    <TableHeader>
      <TableRow>
        <TableHead scope="col" className="w-28">Место</TableHead>
        <TableHead scope="col">Вуз</TableHead>
        <TableHead scope="col" className="hidden w-40 md:table-cell">Из {total}</TableHead>
        <TableHead scope="col" className="text-right">Балл</TableHead>
        <TableHead scope="col" className="text-right" title={`Против места за ${forecast.basePeriod.toLowerCase()}`}>Δ</TableHead>
        {category === "social" ? PLATFORM_COLUMNS.map(([key, label]) =>
          <TableHead key={key} scope="col" className="hidden text-right lg:table-cell">{label}</TableHead>) : null}
        {consolidated ? <TableHead scope="col" className="hidden text-right lg:table-cell" title="Справка: сводный рейтинг не прогнозируется">
          Сводное, {forecast.basePeriod.toLowerCase()}</TableHead> : null}
        {actual ? <><TableHead scope="col" className="text-right">Факт</TableHead>
          <TableHead scope="col" className="text-right" title="Факт минус прогноз: плюс — вуз оказался ниже прогноза">Ошибка</TableHead></> : null}
      </TableRow>
    </TableHeader>
    <TableBody>
      {rowsFor(forecast.rows, category).map((row) => {
        const cell = row.categories[category];
        const note = sourceNote(cell, forecast.basePeriod);
        const name = row.shortName ?? row.name;
        return <TableRow key={row.institutionId} data-testid="rating-row">
          <TableCell className="font-semibold whitespace-nowrap">{rankLabel(cell)}</TableCell>
          <TableCell className="max-w-72 whitespace-normal">
            {row.legacyId ? <Link href={`/institutions/${row.legacyId}`} prefetch={false} title={row.name}
              className="hover:underline focus-visible:underline">{name}</Link> : name}
            {note ? <span className={cn("text-muted-foreground block text-xs", (cell.source === "fallback" || cell.source === "source_zero") && "text-foreground/80")}>{note}</span> : null}
          </TableCell>
          <TableCell className="hidden md:table-cell"><PlaceStrip cell={cell} total={total} /></TableCell>
          <TableCell className="text-right">{cell.score.toFixed(1)}</TableCell>
          <TableCell className="text-right"><Delta value={rankDelta(cell)} /></TableCell>
          {category === "social" ? PLATFORM_COLUMNS.map(([key]) =>
            <TableCell key={key} className="text-muted-foreground hidden text-right lg:table-cell">{row.categories[key].score.toFixed(1)}</TableCell>) : null}
          {consolidated ? <TableCell className="text-muted-foreground hidden text-right lg:table-cell">{row.baseConsolidatedRank ?? "—"}</TableCell> : null}
          {actual ? <>
            <TableCell className="text-right">{cell.actualRank ?? "—"}</TableCell>
            <TableCell className="text-right">{cell.actualRank === null ? "—" : cell.actualRank - cell.rank}</TableCell>
          </> : null}
        </TableRow>;
      })}
    </TableBody>
  </Table>;
}
