import type * as React from "react";
import { ArrowDownToLine, CircleCheck, DatabaseBackup, ListOrdered, RotateCcw, ScanSearch, Sigma, Timer, type LucideIcon } from "lucide-react";
import { PlatformChip } from "@/components/platform-chip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { CatalogStatus, SystemOverview } from "@/lib/catalog-api";
import { PLATFORM_LONG_LABELS } from "@/lib/format";
import { cn } from "@/lib/utils";
import { LazyCollectionChart, LazyHostCards, LazyStorageCards, LazySystemCharts } from "./lazy-charts";
import { LiveHostProvider } from "./live-host";
import { LiveNumber } from "./live-number";
import { RangeSwitch } from "./range-switch";
import { ago, bytes, fields, Pill, plural, Section } from "./shared";

const number = new Intl.NumberFormat("ru-RU");
const TONES = {
  ok: { dot: "bg-success", text: "text-success", label: "в норме" },
  warn: { dot: "bg-warning", text: "text-warning", label: "внимание" },
  fail: { dot: "bg-destructive", text: "text-destructive", label: "сбой" },
  unknown: { dot: "bg-muted-foreground/40", text: "text-muted-foreground", label: "нет данных" },
} as const;

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

type Tone = keyof typeof TONES;
const STATE_TEXT: Record<Tone, string> = { ok: "в норме", warn: "задерживается", fail: "сбой", unknown: "нет данных" };
const BAR: Record<Tone, string> = {
  ok: "[&_[data-slot=progress-indicator]]:bg-success", warn: "[&_[data-slot=progress-indicator]]:bg-warning",
  fail: "[&_[data-slot=progress-indicator]]:bg-destructive", unknown: "",
};

function freshness(at: string | null, limit: number, now: number): { tone: Tone; share: number | null } {
  if (!at) return { tone: "unknown", share: null };
  const age = Math.max(0, (now - Date.parse(at)) / 1000);
  return { tone: age <= limit ? "ok" : age <= 2 * limit ? "warn" : "fail", share: Math.min(100, age * 100 / limit) };
}

function limitText(seconds: number) {
  return seconds < 3600 ? `${Math.round(seconds / 60)} мин` : `${Math.round(seconds / 3600)} ч`;
}

/** Ступень конвейера: значок со статусом, возраст и шкала «сколько прошло от
 *  допустимого перерыва». Зелёная точка пульсирует, пока ступень свежая. */
function Stage({ icon: Icon, label, value, tone, share, note, last }: {
  icon: LucideIcon; label: string; value: React.ReactNode; tone: Tone; share: number | null; note: string; last?: boolean;
}) {
  const colors = TONES[tone];
  return (
    <li className="relative grid grid-cols-[2rem_1fr] gap-3 pb-4 last:pb-0" data-stage={label}>
      {last ? null : <span aria-hidden="true" className="bg-border absolute top-9 bottom-1 left-4 w-px -translate-x-1/2" />}
      <span className={cn("bg-muted relative flex size-8 items-center justify-center rounded-lg", colors.text)}>
        <Icon className="size-4" aria-hidden="true" />
        <span className="absolute -top-0.5 -right-0.5 flex size-2.5" aria-hidden="true">
          {tone === "ok" ? <span className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-50 motion-reduce:hidden", colors.dot)} /> : null}
          <span className={cn("ring-card relative inline-flex size-2.5 rounded-full ring-2", colors.dot)} />
        </span>
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <p className="font-medium">{label}</p>
          <p className="tabular-nums">{value}</p>
        </div>
        <Progress className={cn("my-1.5 [&_[data-slot=progress-track]]:h-1.5 [&_[data-slot=progress-track]]:rounded-full", BAR[tone])}
          aria-label={`${label}: ${STATE_TEXT[tone]}`} value={share} />
        <p className="text-muted-foreground flex flex-wrap justify-between gap-2 text-xs">
          <span>{note}</span><span className={colors.text}>{STATE_TEXT[tone]}</span>
        </p>
      </div>
    </li>
  );
}

function Pipeline({ overview, now }: { overview: SystemOverview; now: number }) {
  const pipeline = overview.pipeline;
  const restarts = Object.entries(overview.restarts);
  const stages: { icon: LucideIcon; label: string; at: string | null; limit: number }[] = pipeline ? [
    { icon: ArrowDownToLine, label: "Приём пакетов с Сервера 1", at: pipeline.ingestAcceptedAt, limit: 20 * 60 },
    { icon: ScanSearch, label: "Анализ публикаций", at: pipeline.analysisCompletedAt, limit: 60 * 60 },
    { icon: Sigma, label: "Пересчёт норм", at: pipeline.normsRunAt, limit: 26 * 3600 },
    { icon: Timer, label: "Профиль позднего отклика", at: pipeline.tailRunAt, limit: 26 * 3600 },
    { icon: DatabaseBackup, label: "Резервная копия", at: pipeline.backupAt, limit: 36 * 3600 },
  ] : [];
  const lag = pipeline?.analysisLagSeconds ?? null;
  const lagTone: Tone = lag == null ? "unknown" : lag <= 3 * 3600 ? "ok" : lag <= 6 * 3600 ? "warn" : "fail";
  const stage = (item: (typeof stages)[number], note: string, last = false) => {
    const { tone, share } = freshness(item.at, item.limit, now);
    return <Stage key={item.label} icon={item.icon} label={item.label} value={ago(item.at, now)} tone={tone} share={share}
      note={`${note}норма — до ${limitText(item.limit)}`} last={last} />;
  };
  return (
    <Section title="Конвейер данных" className="mb-0" description="Шкала — сколько прошло с последнего прохода от допустимого перерыва; за ним — тревога.">
      {pipeline ? <ol className="text-sm" data-testid="pipeline-stages">
        {stages.slice(0, 2).map((item) => stage(item, ""))}
        <Stage icon={ListOrdered} label="Очередь анализа" tone={lagTone} share={lag == null ? null : Math.min(100, lag * 100 / (3 * 3600))}
          value={pipeline.analysisBacklog == null ? "—" : <><LiveNumber value={pipeline.analysisBacklog} /> {plural(pipeline.analysisBacklog, "пост", "поста", "постов")}</>}
          note={`отставание ${lag == null ? "—" : `${Math.round(lag / 60)} мин`} · норма — до 3 ч`} />
        {stages.slice(2).map((item, index, rest) => stage(item, "раз в сутки · ", index === rest.length - 1))}
      </ol> : <p className="text-muted-foreground">Метрик конвейера в снимке нет.</p>}
      <div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-4 text-xs">
        <RotateCcw className="text-muted-foreground size-3.5" aria-hidden="true" />
        <span className="text-muted-foreground">Автоперезапуски служб за период:</span>
        {restarts.length ? restarts.map(([unit, count]) => (
          <Badge key={unit} variant="outline" className="text-warning">{unit.replace(/^m-ranked-target-|\.service$/g, "")} ×{count}</Badge>
        )) : <Badge variant="outline" className="text-success">не было</Badge>}
      </div>
    </Section>
  );
}

function Collection({ overview, now }: { overview: SystemOverview; now: number }) {
  const ok = overview.collection.reduce((sum, row) => sum + row.ok, 0);
  const failed = overview.collection.reduce((sum, row) => sum + row.failed, 0);
  const share = ok + failed ? Math.round(ok * 1000 / (ok + failed)) / 10 : null;
  return (
    <Section title="Сбор за период" className="mb-0" description="Опросы аккаунтов, завершённые за выбранный период: успешные цветом площадки, ошибки — красным."
      action={<Pill className={share !== null && share < 95 ? "text-warning" : "text-success"}>{share === null ? "опросов нет" : `${share.toLocaleString("ru-RU")}% успешно`}</Pill>}>
      <LazyCollectionChart rows={overview.collection} />
      <ul className="mt-3 grid gap-2 sm:grid-cols-2" data-testid="collection-platforms">
        {overview.collection.map((row) => {
          const total = row.ok + row.failed;
          const errors = total ? Math.round(row.failed * 100 / total) : 0;
          return (
            <li key={row.platform} className="flex min-w-0 items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs">
              <PlatformChip platform={row.platform} label={PLATFORM_LONG_LABELS[row.platform]} className="min-w-0" />
              <span className="text-right tabular-nums">
                <b className="text-sm"><LiveNumber value={row.ok} /></b>
                <span className={cn("ml-1.5", errors > 5 ? "text-warning" : "text-muted-foreground")}>· {number.format(row.failed)} ош. · {errors}%</span>
                <span className="text-muted-foreground block">успешный {ago(row.lastOkAt, now)}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function Backups({ backups, now, csrf, canRefresh, outcome }: {
  backups: SystemOverview["backups"]; now: number; csrf: string; canRefresh: boolean; outcome?: string;
}) {
  const state = !backups ? "нет данных"
    : backups.running ? `снимается${backups.partialBytes ? ` · ${bytes(backups.partialBytes)}` : ""}`
      : backups.requested ? "запрошена, начнётся в течение минуты"
        : backups.lastResult && backups.lastResult !== "success" ? `последний запуск не удался (код ${backups.lastExitStatus ?? "—"})` : "готова";
  const busy = !!backups && (backups.running || backups.requested);
  return (
    <Section title="Резервные копии" className="mt-5"
      description="Полный снимок базы (pg_dump, zstd). На основном сервере — самая новая копия; на серверах из политики хранения — она и последняя проверенная восстановлением. Обновление удаляет лишние локальные копии, затем снимает новую. Снимок идёт с ограничением скорости, чтобы не мешать сбору, и может занять до получаса."
      action={<form method="post" action="/manage/backup/refresh">{fields(csrf)}
        <Button type="submit" disabled={!canRefresh || busy} title={canRefresh ? undefined : "Доступно роли ADMIN"}>
          <DatabaseBackup data-icon="inline-start" aria-hidden="true" />{busy ? "Копия обновляется…" : "Обновить резервную копию"}
        </Button>
      </form>}>
      {outcome === "requested" ? <p role="status" className="text-success mb-3">Запрос принят: копия начнёт сниматься в течение минуты.</p>
        : outcome === "unavailable" ? <p role="status" className="text-destructive mb-3">Не удалось передать запрос серверу резервного копирования.</p> : null}
      <p className="mb-3 text-sm">Состояние: <b data-testid="backup-state">{state}</b></p>
      {backups?.files.length ? (
        <Table data-testid="backup-files" containerProps={{ tabIndex: 0, role: "region", "aria-label": "Файлы резервных копий" }}>
          <TableHeader><TableRow><TableHead>Файл</TableHead><TableHead className="text-right">Размер</TableHead><TableHead>Снята</TableHead><TableHead>Проверка</TableHead></TableRow></TableHeader>
          <TableBody>
            {backups.files.map((file) => (
              <TableRow key={file.name}>
                <TableCell className="font-mono text-xs">{file.name}</TableCell>
                <TableCell className="text-right tabular-nums">{bytes(file.bytes)}</TableCell>
                <TableCell>{ago(file.at, now)}</TableCell>
                <TableCell>{file.verified
                  ? <Badge variant="outline" className="text-muted-foreground h-6 gap-1 px-2 text-xs"><CircleCheck aria-hidden="true" className="fill-success text-card size-3.5!" />проверена восстановлением</Badge>
                  : <span className="text-muted-foreground text-xs">—</span>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : <p className="text-muted-foreground">Копий на сервере нет.</p>}
    </Section>
  );
}

const RANGES = [["1h", "1 час"], ["3h", "3 часа"], ["day", "Сутки"], ["week", "Неделя"]] as const;
export type SystemRange = (typeof RANGES)[number][0];

export function SystemTab({ overview, status, range, now, csrf, canRefreshBackup, backupOutcome }: {
  overview: SystemOverview | null; status: CatalogStatus | null; range: SystemRange; now: number;
  csrf: string; canRefreshBackup: boolean; backupOutcome?: string;
}) {
  if (!overview) return <Section title="Состояние системы"><p className="text-destructive">Не удалось получить снимки сервера.</p></Section>;
  const hourly = range === "1h" || range === "3h";
  const step = range === "week" ? "по часу" : range === "day" ? "по пять минут" : "по минуте, а CPU, RAM, сеть и диск — каждые 5 секунд";
  return <LiveHostProvider>
    <Checks checks={overview.checks} />
    {overview.host ? <LazyHostCards host={overview.host} fallback={overview.series} /> : null}
    <LazyStorageCards storage={status?.storage ?? null} />
    <Section title="Динамика" description={overview.sampledAt
      ? `Ресурсы машины — вживую из памяти API, остальное — по снимку сервера раз в минуту (последний — ${ago(overview.sampledAt, now)}). Точки графика ${step}.`
      : "Снимков ещё нет: таймер ops-sample пишет первый в течение минуты."}
      action={<RangeSwitch label="Период" value={range} options={RANGES} href={(value) => `/manage?tab=system&range=${value}`} />}>
      {overview.series.length || hourly ? <LazySystemCharts points={overview.series} range={range} /> : <p className="text-muted-foreground">Точек для графиков пока нет.</p>}
    </Section>
    <div className="grid gap-5 lg:grid-cols-2">
      <Pipeline overview={overview} now={now} />
      <Collection overview={overview} now={now} />
    </div>
    <Backups backups={overview.backups} now={now} csrf={csrf} canRefresh={canRefreshBackup} outcome={backupOutcome} />
  </LiveHostProvider>;
}
