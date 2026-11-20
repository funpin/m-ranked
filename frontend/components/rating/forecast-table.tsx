import Link from "@/components/native-link";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { hasActual, isIncomplete, monthShift, placeGap, rowsFor, signed, sourceNote, stripPosition, viewScore, type RatingView } from "@/lib/rating";
import type { RatingCategory, RatingForecast, RatingForecastCell } from "@/lib/types";
import { cn } from "@/lib/utils";

const PLATFORM_COLUMNS = [["max", "MAX"], ["vk", "VK"], ["rutube", "Rutube"]] as const;

/** Цвет прогноза — тот же оттенок, что точка прогноза на графике (`chart-1`), но
 *  затемнённый на светлой теме: сам `chart-1` даёт тексту контраст 3.7 вместо 4.5. */
export const FORECAST_INK = "text-[color-mix(in_oklch,var(--chart-1)_70%,black)] dark:text-chart-1";

/** Δ — сдвиг против места прошлого опубликованного месяца, стрелками: так он не
 *  путается с ± (разница прогноза и факта, числом со знаком). */
function Delta({ value }: { value: number | null }) {
  if (value === null || value === 0) return <span className="text-muted-foreground">—</span>;
  const label = value > 0 ? `выше на ${value}` : `ниже на ${-value}`;
  return <span aria-label={label} className={value > 0 ? "text-success" : "text-destructive"}>
    {value > 0 ? `↑${value}` : `↓${-value}`}
  </span>;
}

function Gap({ value, view }: { value: number | null; view: RatingView }) {
  if (value === null) return <span className="text-muted-foreground">—</span>;
  const other = view === "fact" ? "прогноз" : "факт";
  const label = value === 0 ? `${other} совпал` : `${other} ${value > 0 ? "выше" : "ниже"} на ${Math.abs(value)}`;
  return <span aria-label={label} className={cn("font-medium", value > 0 ? "text-success" : value < 0 ? "text-destructive" : "text-muted-foreground")}>
    {signed(value)}
  </span>;
}

/** Прогноз — акцентный цвет (как точка прогноза на графике), факт — нейтральный
 *  в обводке (как кольцо факта). Место текущего режима крупнее, второе — тише. */
function ForecastPlace({ cell, primary, basePeriod }: { cell: RatingForecastCell; primary: boolean; basePeriod: string }) {
  return <span className="inline-flex flex-col leading-tight">
    <span className={cn(FORECAST_INK, primary ? "text-base font-semibold" : "text-sm")}><Mark cell={cell} basePeriod={basePeriod} />{cell.rank}</span>
    {primary && cell.rankBest !== cell.rankWorst
      ? <span className="text-muted-foreground text-xs font-normal" title="Места при типичной ошибке прогноза">{cell.rankBest}–{cell.rankWorst}</span>
      : null}
  </span>;
}

function FactPlace({ rank, primary }: { rank: number | null; primary: boolean }) {
  if (rank === null) return <span className="text-muted-foreground">—</span>;
  return <span className={cn("border-foreground/40 inline-flex min-w-8 justify-center rounded-md border px-1.5",
    primary ? "text-foreground text-base font-semibold" : "text-muted-foreground text-sm")}>{rank}</span>;
}

/** Место на шкале всех вузов рейтинга: полоса — диапазон при типичной ошибке,
 *  точка — прогноз, кольцо — факт. Числа стоят рядом текстом, поэтому полоса
 *  скрыта от читалок экрана. */
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

// Чем менее важна колонка, тем раньше она прячется при сужении окна:
// площадки — уже 1280 px, полоса «Из N» — уже 1024 px, Δ — на телефоне.
const HIDE_PLATFORMS = "hidden xl:table-cell";
const HIDE_STRIP = "hidden lg:table-cell";
const HIDE_DELTA = "hidden sm:table-cell";

function score(value: number | null) {
  return value === null ? "—" : value.toFixed(1);
}

/** «*» перед числом прогноза на неполных данных; причина — в подсказке и для читалок. */
function Mark({ cell, basePeriod }: { cell: RatingForecastCell; basePeriod: string }) {
  if (!isIncomplete(cell)) return null;
  const note = sourceNote(cell, basePeriod) ?? "неполные данные";
  return <span title={note} className="text-foreground/80 mr-px"><span aria-hidden="true">*</span><span className="sr-only">{note}: </span></span>;
}

export function ForecastTable({ forecast, category, view, total }: { forecast: RatingForecast; category: RatingCategory; view: RatingView; total: number }) {
  const actual = hasActual(forecast);
  // На узком экране — без слова «Место»: колонки и так видно по цвету и обводке.
  const forecastHead = <TableHead key="forecast" scope="col" className="w-20 sm:w-28">
    <span className={FORECAST_INK}><span className="hidden sm:inline">Место </span><span className="sm:hidden">Прогноз</span></span>
    <span className="text-muted-foreground hidden font-normal sm:inline">(прогноз)</span></TableHead>;
  const factHead = <TableHead key="fact" scope="col" className="w-16 sm:w-24">
    <span className="hidden sm:inline">Место </span><span className="sm:hidden">Факт</span>
    <span className="text-muted-foreground hidden font-normal sm:inline">(факт)</span></TableHead>;
  const gapTitle = view === "fact" ? "Прогноз против факта: плюс — прогноз ставил вуз выше" : "Факт против прогноза: плюс — вуз оказался выше прогноза";
  const deltaTitle = `Против места за ${forecast.basePeriod.toLowerCase()} — ${view === "fact" ? "по факту" : "по прогнозу"}; ↑ — выше`;
  const marked = view === "forecast" && forecast.rows.some((row) => isIncomplete(row.categories[category])
    || (category === "social" && PLATFORM_COLUMNS.some(([key]) => isIncomplete(row.categories[key]))));
  return <>
  <Table className="tabular-nums" data-testid="rating-table" data-view={view}>
    <TableCaption className="sr-only">{view === "fact" ? "Официальные места" : "Прогноз мест"}: {forecast.period}</TableCaption>
    <TableHeader>
      <TableRow>
        {view === "fact" ? [factHead, forecastHead] : actual ? [forecastHead, factHead] : [forecastHead]}
        {actual ? <TableHead scope="col" className="text-right" title={gapTitle}>±</TableHead> : null}
        <TableHead scope="col">Вуз</TableHead>
        <TableHead scope="col" className={cn(HIDE_STRIP, "w-40")} title="Точка — прогноз, кольцо — факт, полоса — диапазон прогноза">Из {total}</TableHead>
        <TableHead scope="col" className={cn(HIDE_DELTA, "text-right")} title={deltaTitle}>Δ</TableHead>
        <TableHead scope="col" className="text-right">Балл</TableHead>
        {category === "social" ? PLATFORM_COLUMNS.map(([key, label]) =>
          <TableHead key={key} scope="col" className={cn(HIDE_PLATFORMS, "text-right")}>{label}</TableHead>) : null}
      </TableRow>
    </TableHeader>
    <TableBody>
      {rowsFor(forecast.rows, category, view).map((row) => {
        const cell = row.categories[category];
        const name = row.shortName ?? row.name;
        const forecastCell = <TableCell key="forecast"><ForecastPlace cell={cell} primary={view === "forecast"} basePeriod={forecast.basePeriod} /></TableCell>;
        const factCell = <TableCell key="fact"><FactPlace rank={cell.actualRank} primary={view === "fact"} /></TableCell>;
        return <TableRow key={row.institutionId} data-testid="rating-row">
          {view === "fact" ? [factCell, forecastCell] : actual ? [forecastCell, factCell] : [forecastCell]}
          {actual ? <TableCell className="text-right"><Gap value={placeGap(cell, view)} view={view} /></TableCell> : null}
          <TableCell className="max-w-72 min-w-28 whitespace-normal">
            {row.legacyId ? <Link href={`/institutions/${row.legacyId}`} prefetch={false} title={row.name}
              className="hover:underline focus-visible:underline">{name}</Link> : name}
            {row.shortName && row.shortName !== row.name ? <span className="text-muted-foreground block text-xs">{row.name}</span> : null}
          </TableCell>
          <TableCell className={HIDE_STRIP}><PlaceStrip cell={cell} total={total} /></TableCell>
          <TableCell className={cn(HIDE_DELTA, "text-right")}><Delta value={monthShift(cell, view)} /></TableCell>
          <TableCell className="text-right">{view === "forecast" ? <Mark cell={cell} basePeriod={forecast.basePeriod} /> : null}{score(viewScore(cell, view))}</TableCell>
          {category === "social" ? PLATFORM_COLUMNS.map(([key]) =>
            <TableCell key={key} className={cn(HIDE_PLATFORMS, "text-muted-foreground text-right")}>
              {view === "forecast" ? <Mark cell={row.categories[key]} basePeriod={forecast.basePeriod} /> : null}{score(viewScore(row.categories[key], view))}</TableCell>) : null}
        </TableRow>;
      })}
    </TableBody>
  </Table>
  {marked ? <p data-testid="rating-incomplete-note" className="text-muted-foreground mt-2 text-xs">
    * — неполные данные: нашей истории за месяц не хватает, балл площадки взят за {forecast.basePeriod.toLowerCase()};
    у балла соцсетей — так посчитана часть площадок. Подробности — в подсказке у звёздочки.</p> : null}
  </>;
}
