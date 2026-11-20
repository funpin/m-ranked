import Link from "@/components/native-link";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ScoreBar } from "@/components/rating/formula-visual";
import { OWN_PLATFORMS, partialNote, platformTitle, rawShift, removedNote, type OwnPlatformKey } from "@/lib/own-rating";
import type { OwnRating, OwnRatingPlatform, OwnRatingRow } from "@/lib/types";
import { cn } from "@/lib/utils";

// Чем менее важна колонка, тем раньше она прячется при сужении окна:
// площадки — уже 1024 px, «Без очистки» — на телефоне.
const HIDE_PLATFORMS = "hidden lg:table-cell";
const HIDE_RAW = "hidden sm:table-cell";

const RAW_TITLE = "Место по той же формуле, если засчитать всё, включая статистически необычную активность";

/** Балл площадки полоской её цвета; бледный хвост — сколько было бы без очистки. */
function PlatformCell({ item, platform }: { item: OwnRatingPlatform; platform: OwnPlatformKey }) {
  const removed = removedNote(item);
  const title = [platformTitle(item), removed].filter(Boolean).join(". ");
  return <>
    <ScoreBar value={item.score} platform={platform} ghost={item.rawScore} title={title} />
    {removed ? <span className="sr-only">{removed}</span> : null}
  </>;
}

function RawPlace({ row }: { row: OwnRatingRow }) {
  const shift = rawShift(row);
  if (shift === 0) return <span className="text-muted-foreground">{row.rawRank}</span>;
  const label = shift > 0 ? `без очистки выше на ${shift}` : `без очистки ниже на ${-shift}`;
  return <span className="inline-flex flex-col leading-tight">
    <span>{row.rawRank}</span>
    <span aria-label={label} className="text-muted-foreground text-xs">{shift > 0 ? `↑${shift}` : `↓${-shift}`}</span>
  </span>;
}

/** «*» перед местом на неполных данных; причина — в подсказке и для читалок. */
function Mark({ row }: { row: OwnRatingRow }) {
  if (!row.partial) return null;
  const note = partialNote(row) ?? "неполные данные";
  return <span title={note} className="text-foreground/80 mr-px"><span aria-hidden="true">*</span><span className="sr-only">{note}: </span></span>;
}

export function OwnTable({ own }: { own: OwnRating }) {
  return <Table className="tabular-nums" data-testid="own-table">
    <TableCaption className="sr-only">Наш рейтинг вузов по соцсетям: {own.period}</TableCaption>
    <TableHeader>
      <TableRow>
        <TableHead scope="col" className="w-16">Место</TableHead>
        <TableHead scope="col">Вуз</TableHead>
        <TableHead scope="col">Балл</TableHead>
        {OWN_PLATFORMS.map(({ key, label }) => <TableHead key={key} scope="col" className={HIDE_PLATFORMS}>{label}</TableHead>)}
        <TableHead scope="col" className={cn(HIDE_RAW, "w-24")} title={RAW_TITLE}>Без очистки</TableHead>
      </TableRow>
    </TableHeader>
    <TableBody>
      {own.rows.map((row) => {
        const name = row.shortName ?? row.name;
        return <TableRow key={row.institutionId} data-testid="own-row">
          <TableCell className="text-base font-semibold"><Mark row={row} />{row.rank}</TableCell>
          <TableCell className="max-w-72 min-w-28 whitespace-normal">
            {row.legacyId ? <Link href={`/institutions/${row.legacyId}`} prefetch={false} title={row.name}
              className="hover:underline focus-visible:underline">{name}</Link> : name}
            {row.shortName && row.shortName !== row.name ? <span className="text-muted-foreground block text-xs">{row.name}</span> : null}
          </TableCell>
          <TableCell className="w-36 font-semibold"><ScoreBar value={row.score} title={`Без очистки ${row.rawScore.toFixed(1)}`} ghost={row.rawScore} /></TableCell>
          {OWN_PLATFORMS.map(({ key }) => <TableCell key={key} className={cn(HIDE_PLATFORMS, "w-32")}>
            <PlatformCell item={row.platforms[key]} platform={key} />
          </TableCell>)}
          <TableCell className={HIDE_RAW}><RawPlace row={row} /></TableCell>
        </TableRow>;
      })}
    </TableBody>
  </Table>;
}
