import type * as React from "react";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { CatalogStatus, SystemOverview } from "@/lib/catalog-api";
import { PLATFORM_LONG_LABELS } from "@/lib/format";
import { cn } from "@/lib/utils";
import { LazySystemCharts } from "./lazy-charts";
import { LiveNumber } from "./live-number";
import { RangeSwitch } from "./range-switch";
import { ago, bytes, Pill, plural, Section } from "./shared";

const number = new Intl.NumberFormat("ru-RU");
const TONES = {
  ok: { dot: "bg-success", text: "text-success", label: "в норме" },
  warn: { dot: "bg-warning", text: "text-warning", label: "внимание" },
  fail: { dot: "bg-destructive", text: "text-destructive", label: "сбой" },
  unknown: { dot: "bg-muted-foreground/40", text: "text-muted-foreground", label: "нет данных" },
} as const;

function percent(part: number | null | undefined, total: number | null | undefined, digits = 1) {
  return part != null && total ? Number((part * 100 / total).toFixed(digits)) : null;
}

function Checks({ checks }: { checks: SystemOverview["checks"] }) {
  const problems = checks.filter((check) => check.state === "warn" || check.state === "fail").length;
  return (
    <Section title="Проверки" description="Те же пороги, что у тревог в Telegram: сбор по площадкам, приём с Сервера 1, анализ, службы, ресурсы и резервные копии."
      action={<Pill className={problems ? "text-warning" : "text-success"}>{problems ? `${problems} ${plural(problems, "требует", "требуют", "требуют")} внимания` : "Всё в порядке"}</Pill>}>
      <ul data-testid="system-checks" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {checks.map((check) => {
          const tone = TONES[check.state];
          return (
            <li key={check.key} className="flex min-w-0 items-start gap-3 rounded-lg border p-3">
              <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", tone.dot)} aria-hidden="true" />
              <div className="min-w-0">
                <p className="text-sm font-medium">{check.label} <span className={cn("sr-only", tone.text)}>— {tone.label}</span></p>
                <p className="text-muted-foreground truncate text-xs" title={check.detail}>{check.detail}</p>
              </div>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function Gauge({ label, value, detail, share }: { label: string; value: React.ReactNode; detail: string; share: number | null }) {
  return (
    <Card className="block min-w-0 p-5">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-muted-foreground text-xs font-medium">{label}</p>
        <p className="font-heading text-xl font-semibold tabular-nums">{value}</p>
      </div>
      <Progress className="my-3 [&_[data-slot=progress-track]]:h-1.5 [&_[data-slot=progress-track]]:rounded-full" aria-label={label}
        value={share === null ? null : Math.min(100, share)} />
      <p className="text-muted-foreground text-xs">{detail}</p>
    </Card>
  );
}

function Host({ host }: { host: NonNullable<SystemOverview["host"]> }) {
  const cores = host.cores ?? 1;
  const load = host.load[1] ?? null;
  const memory = percent(host.memoryUsedBytes, host.memoryTotalBytes, 0);
  const diskUsed = host.diskTotalBytes != null && host.diskFreeBytes != null ? host.diskTotalBytes - host.diskFreeBytes : null;
  return (
    <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Gauge label="Процессор" value={host.cpuPercent == null ? "—" : <LiveNumber value={host.cpuPercent} decimals={1} suffix="%" />} share={host.cpuPercent}
        detail={`load average ${host.load.map((value) => value.toFixed(2)).join(" · ")} на ${cores} ${cores === 1 ? "ядро" : "ядра"}`} />
      <Gauge label="Память" value={memory == null ? "—" : <LiveNumber value={memory} suffix="%" />} share={memory}
        detail={`${bytes(host.memoryUsedBytes)} из ${bytes(host.memoryTotalBytes)}${host.swapUsedBytes ? ` · подкачка ${bytes(host.swapUsedBytes)}` : ""}`} />
      <Gauge label="Диск" value={`${bytes(host.diskFreeBytes)} свободно`} share={percent(diskUsed, host.diskTotalBytes)}
        detail={`занято ${bytes(diskUsed)} из ${bytes(host.diskTotalBytes)}`} />
      <Gauge label="Службы" value={host.unitsActive == null ? "—" : <><LiveNumber value={host.unitsActive} /> из {host.unitsTotal ?? "—"}</>}
        share={percent(host.unitsActive, host.unitsTotal)}
        detail={host.failedUnits.length ? `упали: ${host.failedUnits.join(", ")}` : load !== null && load > cores * 2 ? "нагрузка выше двух на ядро" : "упавших нет"} />
    </div>
  );
}

function Pipeline({ overview, now }: { overview: SystemOverview; now: number }) {
  const pipeline = overview.pipeline;
  const rows: [string, string][] = pipeline ? [
    ["Последний пакет с Сервера 1", ago(pipeline.ingestAcceptedAt, now)],
    ["Последний пакет анализа", ago(pipeline.analysisCompletedAt, now)],
    ["Очередь анализа", pipeline.analysisBacklog == null ? "—" : `${number.format(pipeline.analysisBacklog)} постов · отставание ${pipeline.analysisLagSeconds == null ? "—" : `${Math.round(pipeline.analysisLagSeconds / 60)} мин`}`],
    ["Пересчёт норм", ago(pipeline.normsRunAt, now)],
    ["Профиль позднего отклика", ago(pipeline.tailRunAt, now)],
    ["Резервная копия", ago(pipeline.backupAt, now)],
  ] : [];
  const restarts = Object.entries(overview.restarts);
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Section title="Конвейер данных" className="mb-0">
        <dl className="divide-y text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="flex items-baseline justify-between gap-3 py-2">
              <dt className="text-muted-foreground">{label}</dt><dd className="text-right tabular-nums">{value}</dd>
            </div>
          ))}
          <div className="flex items-baseline justify-between gap-3 py-2">
            <dt className="text-muted-foreground">Автоперезапуски служб за период</dt>
            <dd className="text-right">{restarts.length ? restarts.map(([unit, count]) => `${unit.replace(/^m-ranked-target-|\.service$/g, "")} ×${count}`).join(", ") : "не было"}</dd>
          </div>
        </dl>
      </Section>
      <Section title="Сбор за период" className="mb-0" description="Опросы аккаунтов, завершённые за выбранный период.">
        {/* Узкая колонка прокручивается сама; с клавиатуры до прокрутки
            достают через фокус на области. */}
        <div tabIndex={0} role="region" aria-label="Сбор по площадкам" className="focus-visible:ring-ring/50 overflow-x-auto rounded-md outline-none focus-visible:ring-2 [&_[data-slot=table-container]]:overflow-visible">
        <Table>
          <TableHeader><TableRow><TableHead>Площадка</TableHead><TableHead className="text-right">Успешно</TableHead><TableHead className="text-right">С ошибкой</TableHead><TableHead className="text-right">Последний успешный</TableHead></TableRow></TableHeader>
          <TableBody>
            {overview.collection.map((row) => {
              const total = row.ok + row.failed;
              return (
                <TableRow key={row.platform}>
                  <TableCell className="font-medium">{PLATFORM_LONG_LABELS[row.platform]}</TableCell>
                  <TableCell className="text-right"><LiveNumber value={row.ok} /></TableCell>
                  <TableCell className={cn("text-right tabular-nums", row.failed && total && row.failed / total > 0.05 ? "text-warning" : "")}>
                    {number.format(row.failed)}{total ? ` · ${Math.round(row.failed * 100 / total)}%` : ""}
                  </TableCell>
                  <TableCell className="text-right">{ago(row.lastOkAt, now)}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        </div>
      </Section>
    </div>
  );
}

function Storage({ status }: { status: CatalogStatus | null }) {
  const storage = status?.storage, total = storage?.diskTotalBytes ?? null, free = storage?.diskFreeBytes ?? null;
  const used = total !== null && free !== null ? Math.max(0, total - free) : null;
  const parts = storage?.projectParts;
  const rows = [
    { name: "Диск сервера", value: `${bytes(used)} из ${bytes(total)}`, percent: percent(used, total), note: "раздела занято", kind: "disk" },
    { name: "Весь проект m-ranked", value: bytes(storage?.projectBytes), percent: percent(storage?.projectBytes, used), note: "от занятого места на диске", kind: "project",
      detail: parts ? `релизы ${bytes(parts.releasesBytes)} · данные служб ${bytes(parts.stateBytes)} · кэш страниц ${bytes(parts.pageCacheBytes)} · база ${bytes(storage?.databaseBytes)}` : null },
    { name: "База результатов парсинга", value: bytes(storage?.databaseBytes), percent: percent(storage?.databaseBytes ?? null, used), note: "от занятого места на диске", kind: "database" },
  ];
  return (
    <Section title="Использование хранилища" className="mt-5"
      description="Проект — релизы, данные служб, кэш страниц nginx и база. Каталоги меряются раз в 6 часов, доли считаются от занятого места на разделе."
      action={<Pill>Свободно {bytes(free)}</Pill>}>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((row) => (
          <article key={row.kind} data-storage={row.kind} className="min-w-0 rounded-lg border p-4">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2 text-xs"><span>{row.name}</span><b>{row.value}</b></div>
            <Progress className="my-2 [&_[data-slot=progress-track]]:h-2 [&_[data-slot=progress-track]]:rounded-full" aria-label={row.name}
              value={row.percent === null ? null : Math.min(100, row.percent)} />
            <small className="text-muted-foreground block text-xs">{row.percent === null ? row.kind === "project" ? "Первый замер каталогов — с первым снимком сервера" : "Размер не предоставлен сервером" : `${row.percent}% ${row.note}`}</small>
            {"detail" in row && row.detail ? <small className="text-muted-foreground mt-1 block text-xs">{row.detail}</small> : null}
          </article>
        ))}
      </div>
    </Section>
  );
}

export function SystemTab({ overview, status, range, now }: {
  overview: SystemOverview | null; status: CatalogStatus | null; range: "day" | "week"; now: number;
}) {
  if (!overview) return <Section title="Состояние системы"><p className="text-destructive">Не удалось получить снимки сервера.</p></Section>;
  return <>
    <Checks checks={overview.checks} />
    {overview.host ? <Host host={overview.host} /> : null}
    <Section title="Динамика" description={overview.sampledAt ? `Снимок сервера раз в минуту, последний — ${ago(overview.sampledAt, now)}. Точки графика за сутки — по пять минут.` : "Снимков ещё нет: таймер ops-sample пишет первый в течение минуты."}
      action={<RangeSwitch label="Период" value={range} options={[["day", "Сутки"], ["week", "Неделя"]] as const}
        href={(value) => `/manage?tab=system&range=${value}`} />}>
      {overview.series.length ? <LazySystemCharts points={overview.series} range={range} /> : <p className="text-muted-foreground">Точек для графиков пока нет.</p>}
    </Section>
    <Pipeline overview={overview} now={now} />
    <Storage status={status} />
  </>;
}
