import Link from "@/components/native-link";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { RatingClean, RatingCleanPlatform, RatingCleanRow } from "@/lib/types";
import { cn } from "@/lib/utils";

const PLATFORMS = [["vk", "VK"], ["max", "MAX"]] as const;
const HIDE_PLATFORMS = "hidden lg:table-cell";
const HIDE_BASE = "hidden sm:table-cell";

function percent(part: number, whole: number): number {
  return whole > 0 ? Math.round((100 * part) / whole) : 0;
}

/** Места: насколько вуз опустился бы без накрутки (↓) или поднялся, обогнав накрученных (↑). */
export function placeShift(row: RatingCleanRow): number {
  const social = row.categories.social;
  return social ? social.baseRank - social.rank : 0;
}

function Shift({ value }: { value: number }) {
  if (value === 0) return <span className="text-muted-foreground">—</span>;
  const label = value > 0 ? `выше на ${value}` : `ниже на ${-value}`;
  return <span aria-label={label} className={cn("font-medium", value > 0 ? "text-success" : "text-destructive")}>
    {value > 0 ? `↑${value}` : `↓${-value}`}
  </span>;
}

/** Что убрано на площадке: доли реакций и просмотров, балл площадки до и после. */
function Removed({ item }: { item: RatingCleanPlatform | null | undefined }) {
  if (!item) return <span className="text-muted-foreground">—</span>;
  const reactions = percent(item.removedReactions, item.interactions);
  const smart = percent(item.smartReactions, item.interactions);
  const views = percent(item.removedViews, item.views);
  if (!reactions && !smart && !views) return <span className="text-muted-foreground">не найдено</span>;
  const parts = [reactions ? `реакции −${reactions} %` : null, smart ? `хвост −${smart} %` : null, views ? `просмотры −${views} %` : null]
    .filter(Boolean);
  const smartTitle = item.smart
    ? `Ровный отклик (разброс ${item.smart.evenness.toFixed(2)}) и длинный хвост: поздних реакций на просмотр в ${item.smart.tailRatio.toFixed(1)} раза больше ранних при 90-м перцентиле площадки ${item.smart.tailP90.toFixed(2)}`
    : undefined;
  return <span className="inline-flex flex-col leading-tight" title={smartTitle}>
    <span>{parts.join(" · ")}</span>
    <span className="text-muted-foreground text-xs">балл {item.rawScore.toFixed(1)} → {item.cleanScore.toFixed(1)}</span>
  </span>;
}

export function CleanTable({ clean, rows }: { clean: RatingClean; rows: RatingCleanRow[] }) {
  const basis = clean.basis === "fact" ? "факт" : "прогноз";
  return <Table className="tabular-nums" data-testid="clean-table">
    <TableCaption className="sr-only">М-Рейтинг без накрутки: {clean.period}</TableCaption>
    <TableHeader>
      <TableRow>
        <TableHead scope="col" className="w-20">Место <span className="text-muted-foreground font-normal">без накрутки</span></TableHead>
        <TableHead scope="col" className={cn(HIDE_BASE, "w-24")}>М-Рейтинг <span className="text-muted-foreground font-normal">({basis})</span></TableHead>
        <TableHead scope="col" className="text-right" title="↓ — без накрутки вуз ниже, ↑ — выше: обогнал тех, кто опустился">Сдвиг</TableHead>
        <TableHead scope="col">Вуз</TableHead>
        <TableHead scope="col" className="text-right">Балл соцсетей</TableHead>
        {PLATFORMS.map(([key, label]) => <TableHead key={key} scope="col" className={HIDE_PLATFORMS}>{label}: убрано</TableHead>)}
      </TableRow>
    </TableHeader>
    <TableBody>
      {rows.map((row) => {
        const social = row.categories.social!;
        const name = row.shortName ?? row.name;
        return <TableRow key={row.institutionId} data-testid="clean-row">
          <TableCell className="text-base font-semibold">{social.rank}</TableCell>
          <TableCell className={cn(HIDE_BASE, "text-muted-foreground")}>{social.baseRank}</TableCell>
          <TableCell className="text-right"><Shift value={placeShift(row)} /></TableCell>
          <TableCell className="max-w-72 min-w-28 whitespace-normal">
            {row.legacyId ? <Link href={`/institutions/${row.legacyId}`} prefetch={false} title={row.name}
              className="hover:underline focus-visible:underline">{name}</Link> : name}
            {row.shortName && row.shortName !== row.name ? <span className="text-muted-foreground block text-xs">{row.name}</span> : null}
          </TableCell>
          <TableCell className="text-right whitespace-nowrap">
            {social.baseScore !== social.score
              ? <><span className="text-muted-foreground">{social.baseScore.toFixed(1)} → </span>{social.score.toFixed(1)}</>
              : social.score.toFixed(1)}
          </TableCell>
          {PLATFORMS.map(([key]) => <TableCell key={key} className={cn(HIDE_PLATFORMS, "text-sm")}><Removed item={row.platforms[key]} /></TableCell>)}
        </TableRow>;
      })}
    </TableBody>
  </Table>;
}
