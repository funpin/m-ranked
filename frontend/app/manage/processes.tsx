import type * as React from "react";
import { ArrowUpFromLine, CalendarClock, CircleAlert, CirclePause, Cog, LoaderCircle, RotateCcw, Unplug, type LucideIcon } from "lucide-react";
import Link from "@/components/native-link";
import { PlatformChip } from "@/components/platform-chip";
import { Progress } from "@/components/ui/progress";
import type { CollectorCycle, CollectorsOverview, MeasurementGap, MeasurementGaps, ServerItem, ServerStatus, ServerTask } from "@/lib/catalog-api";
import { PLATFORM_LONG_LABELS } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ago, Pill, plural } from "./shared";

const number = new Intl.NumberFormat("ru-RU");
const MOSCOW_TIME = new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

/** Состояние сервера: цвет точки и текста; «обновляется» крутится. */
export const SERVER_TONE: Record<ServerStatus["state"], { dot: string; text: string; icon: LucideIcon }> = {
  ok: { dot: "bg-success", text: "text-success", icon: Cog },
  updating: { dot: "bg-warning", text: "text-warning", icon: LoaderCircle },
  restarted: { dot: "bg-chart-2", text: "text-chart-2", icon: RotateCcw },
  degraded: { dot: "bg-destructive", text: "text-destructive", icon: CircleAlert },
  offline: { dot: "bg-destructive", text: "text-destructive", icon: Unplug },
};

export function duration(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  if (seconds < 90) return `${Math.round(seconds)} с`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} мин`;
  if (seconds < 2 * 86400) return `${(seconds / 3600).toFixed(1).replace(".", ",")} ч`;
  return `${Math.round(seconds / 86400)} сут`;
}

/** «через 12 мин» до момента в будущем. */
function until(value: string | null, now: number) {
  if (!value) return null;
  const seconds = (Date.parse(value) - now) / 1000;
  return seconds <= 0 ? "сейчас" : `через ${duration(seconds)}`;
}

export function ServerStatusPill({ status, now, className }: { status: ServerStatus; now: number; className?: string }) {
  const tone = SERVER_TONE[status.state];
  const Icon = tone.icon;
  const since = status.since && status.state !== "ok" ? ` · ${ago(status.since, now)}` : "";
  return <Pill className={cn(tone.text, className)}>
    <Icon className={cn("size-3.5", status.state === "updating" && "animate-spin motion-reduce:animate-none")} aria-hidden="true" />
    {status.label}{since}
  </Pill>;
}

/** Переключатель серверов ссылками: кнопок столько, сколько серверов
 *  подключено; у каждой — состояние точкой и версия. */
export function ServerSwitch({ servers, selected, href, label, now }: {
  servers: ServerItem[]; selected: string | null; href: (id: string) => string; label: string; now: number;
}) {
  return (
    <nav aria-label={label} className="mb-5 flex flex-wrap gap-2" data-testid="server-switch">
      {servers.map((server) => {
        const tone = SERVER_TONE[server.status.state];
        const current = server.id === selected;
        return (
          <Link key={server.id} href={href(server.id)} prefetch={false} aria-current={current ? "page" : undefined}
            className={cn("bg-card flex min-w-0 items-center gap-3 rounded-lg border px-4 py-2.5 text-left no-underline transition-colors",
              current ? "border-foreground/40 ring-foreground/10 shadow-sm ring-2" : "text-muted-foreground hover:border-foreground/25 hover:text-foreground")}>
            <span className="relative flex size-2.5 shrink-0" aria-hidden="true">
              {server.status.state === "ok" ? <span className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-50 motion-reduce:hidden", tone.dot)} /> : null}
              <span className={cn("relative inline-flex size-2.5 rounded-full", tone.dot)} />
            </span>
            <span className="min-w-0">
              <span className={cn("block text-sm font-medium", current && "text-foreground")}>{server.displayName}</span>
              <span className="text-muted-foreground block text-xs">
                <span className={tone.text}>{server.status.label}</span>
                {server.status.since && server.status.state !== "ok" ? ` · ${ago(server.status.since, now)}` : ""}
                {server.status.release ? ` · ${server.status.release}` : ""}
              </span>
            </span>
          </Link>
        );
      })}
    </nav>
  );
}

const TASK_NAMES: Record<string, string> = {
  api: "API", web: "Сайт", "transfer-ingest": "Приём пакетов", "anomaly-analysis": "Анализ публикаций",
  "telegram-bot": "Телеграм-бот", redis: "Redis", "cache-warmup": "Прогрев кэша", "ops-sample": "Снимок сервера",
  alerts: "Тревоги", "anomaly-norms": "Пересчёт норм", "anomaly-tail": "Профиль позднего отклика",
  "anomaly-m0-rollup": "Свёртка нулевого месяца", "dump-backup": "Резервная копия", "history-compaction": "Упаковка истории",
  "history-pages": "Страницы истории", "host-storage-gc": "Чистка диска", maintenance: "Обслуживание базы",
  "overview-metrics": "Метрики обзора", "pitr-drill": "Учение восстановления", "rating-forecast": "Прогноз рейтинга",
  reindex: "Переиндексация", "restore-verify": "Проверка восстановлением", "storage-guard": "Сторож диска",
  "storage-main": "Агент хранилища", "node-agent": "Агент узла", "web-cache-gc": "Чистка кэша страниц",
  contributors: "Участники", "transfer-sender": "Отправитель переноса", "collector-watchdog": "Сторож сборщиков",
  "collector@telegram": "Сборщик Telegram", "collector@vk": "Сборщик ВКонтакте", "collector@max": "Сборщик MAX",
  "collector@rutube": "Сборщик Rutube", "backup@daily": "Копия за сутки", "backup@weekly": "Копия за неделю",
  "backup@monthly": "Копия за месяц",
};

const running = (task: ServerTask) => task.active === "activating" || task.active === "reloading"
  || (task.scheduled && task.active === "active" && task.sub !== "exited");

function taskLine(task: ServerTask, now: number): { tone: string; dot: string; text: string; icon?: LucideIcon } {
  if (task.active === "failed") return { tone: "text-destructive", dot: "bg-destructive", text: "упала", icon: CircleAlert };
  if (running(task)) return { tone: "text-chart-2", dot: "bg-chart-2", text: `идёт ${task.startedAt ? duration((now - Date.parse(task.startedAt)) / 1000) : "сейчас"}`, icon: LoaderCircle };
  if (!task.scheduled) {
    return task.active === "active"
      ? { tone: "text-success", dot: "bg-success", text: `работает ${task.since ? duration((now - Date.parse(task.since)) / 1000) : ""}`.trim() }
      : { tone: "text-muted-foreground", dot: "bg-muted-foreground/40", text: "остановлена", icon: CirclePause };
  }
  const failed = task.result && task.result !== "success";
  return { tone: failed ? "text-warning" : "text-muted-foreground", dot: failed ? "bg-warning" : "bg-success",
    text: `${task.lastAt ? ago(task.lastAt, now) : "не запускалось"}${failed ? ` · ${task.result === "exit-code" ? "с ошибкой" : task.result}` : ""}` };
}

function TaskRow({ task, now }: { task: ServerTask; now: number }) {
  const line = taskLine(task, now);
  const Icon = line.icon;
  const next = task.scheduled ? until(task.nextAt, now) : null;
  return (
    <li className="flex min-w-0 items-center gap-3 py-1.5" data-task={task.unit}>
      <span className={cn("size-2 shrink-0 rounded-full", line.dot)} aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate" title={`${task.unit}${next ? ` · следующий запуск ${next}` : ""}`}>{TASK_NAMES[task.unit] ?? task.unit}</span>
      {task.restarts ? <span className="text-warning shrink-0 text-xs tabular-nums" title="Автоперезапуски с последнего ручного">↻{task.restarts}</span> : null}
      <span className={cn("inline-flex shrink-0 items-center gap-1 text-xs tabular-nums", line.tone)}>
        {Icon ? <Icon className={cn("size-3.5", Icon === LoaderCircle && "animate-spin motion-reduce:animate-none")} aria-hidden="true" /> : null}
        {line.text}
      </span>
      {next ? <span className="text-muted-foreground hidden w-24 shrink-0 text-right text-xs tabular-nums 2xl:inline" title="Следующий запуск">{next}</span> : null}
    </li>
  );
}

/** Службы и задания сервера: сначала то, что требует внимания или идёт
 *  сейчас, затем службы, затем расписание. */
export function TaskList({ tasks, now, empty = "Агент сервера ещё не прислал список служб." }: { tasks: ServerTask[]; now: number; empty?: string }) {
  if (!tasks.length) return <p className="text-muted-foreground">{empty}</p>;
  const urgent = (task: ServerTask) => task.active === "failed" ? 0 : running(task) ? 1 : 2;
  const services = tasks.filter((task) => !task.scheduled).sort((a, b) => urgent(a) - urgent(b));
  const scheduled = tasks.filter((task) => task.scheduled).sort((a, b) => urgent(a) - urgent(b)
    || Date.parse(b.lastAt ?? "1970-01-01") - Date.parse(a.lastAt ?? "1970-01-01"));
  const now_ = tasks.filter((task) => running(task)).length;
  return (
    <div className="grid gap-x-8 gap-y-4 md:grid-cols-2" data-testid="task-list">
      <div className="min-w-0">
        <p className="text-muted-foreground mb-1 flex items-center gap-1.5 text-xs font-medium tracking-wide uppercase"><Cog className="size-3.5" aria-hidden="true" />Службы</p>
        <ul className="divide-y">{services.map((task) => <TaskRow key={task.unit} task={task} now={now} />)}</ul>
      </div>
      <div className="min-w-0">
        <p className="text-muted-foreground mb-1 flex items-center justify-between gap-1.5 text-xs font-medium tracking-wide uppercase">
          <span className="flex items-center gap-1.5"><CalendarClock className="size-3.5" aria-hidden="true" />По расписанию</span>
          {now_ ? <span className="text-chart-2 normal-case">{now_} {plural(now_, "идёт", "идут", "идут")} сейчас</span> : null}
        </p>
        <ul className="divide-y">{scheduled.map((task) => <TaskRow key={task.unit} task={task} now={now} />)}</ul>
      </div>
    </div>
  );
}

function gapRange(gap: MeasurementGap) {
  const from = gap.from ? MOSCOW_TIME.format(new Date(gap.from)) : "—";
  return gap.to ? `${from} — ${MOSCOW_TIME.format(new Date(gap.to)).slice(-5)}` : `с ${from}`;
}

/** Пропуски замеров за период: когда, сколько и почему (обновление версии). */
export function GapList({ gaps, what = "замеров", compact = false }: { gaps: MeasurementGap[]; what?: string; compact?: boolean }) {
  if (!gaps.length) return <p className="text-success text-xs">Пропусков {what} нет.</p>;
  return (
    <ul className={cn("grid gap-1.5", compact ? "text-xs" : "text-sm")} data-testid="measurement-gaps">
      {gaps.map((gap, index) => (
        <li key={`${gap.from}-${index}`} className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <span className={cn("size-2 shrink-0 self-center rounded-full", gap.to ? "bg-warning" : "bg-destructive")} aria-hidden="true" />
          <span className="tabular-nums">{gapRange(gap)}</span>
          <b className="font-medium tabular-nums">{duration(gap.seconds)}</b>
          <span className="text-muted-foreground min-w-0">{gap.to ? gap.cause ?? "причина не записана" : "идёт сейчас"}</span>
        </li>
      ))}
    </ul>
  );
}

export function GapSummary({ gaps }: { gaps: MeasurementGaps }) {
  return <Pill className={gaps.count ? "text-warning" : "text-success"}>
    {gaps.count ? `${gaps.count} ${plural(gaps.count, "пропуск", "пропуска", "пропусков")} · ${duration(gaps.seconds)}` : "без пропусков"}
  </Pill>;
}

function Fact({ label, children, tone }: { label: string; children: React.ReactNode; tone?: string }) {
  return <div className="min-w-0"><dt className="text-muted-foreground text-xs">{label}</dt><dd className={cn("font-medium tabular-nums", tone)}>{children}</dd></div>;
}

/** Площадка сборщика: идёт ли цикл, когда был успешный, сколько циклов и
 *  ошибок за период, отставание от расписания и пропуски сбора. */
function Cycle({ cycle, now }: { cycle: CollectorCycle; now: number }) {
  const last = cycle.lastSuccessAt ?? cycle.lastCompletedAt;
  const age = last ? Math.max(0, (now - Date.parse(last)) / 1000) : null;
  const tone = age == null ? "text-muted-foreground" : age <= cycle.freshnessSeconds ? "text-success" : age <= 2 * cycle.freshnessSeconds ? "text-warning" : "text-destructive";
  const bar = age == null ? "" : age <= cycle.freshnessSeconds ? "[&_[data-slot=progress-indicator]]:bg-success"
    : age <= 2 * cycle.freshnessSeconds ? "[&_[data-slot=progress-indicator]]:bg-warning" : "[&_[data-slot=progress-indicator]]:bg-destructive";
  const failedShare = cycle.runs ? Math.round(cycle.failed * 100 / cycle.runs) : 0;
  return (
    <article className="min-w-0 rounded-lg border p-4" data-platform={cycle.platform}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <PlatformChip platform={cycle.platform} label={PLATFORM_LONG_LABELS[cycle.platform]} />
        {cycle.runningSince
          ? <span className="text-chart-2 inline-flex items-center gap-1 text-xs"><LoaderCircle className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />цикл идёт {duration((now - Date.parse(cycle.runningSince)) / 1000)}</span>
          : <span className="text-muted-foreground text-xs">ждёт слота</span>}
      </div>
      <p className="flex items-baseline justify-between gap-2 text-sm"><span>Успешный опрос</span><b className={cn("tabular-nums", tone)}>{ago(last, now)}</b></p>
      <Progress className={cn("my-1.5 [&_[data-slot=progress-track]]:h-1.5 [&_[data-slot=progress-track]]:rounded-full", bar)}
        aria-label={`${PLATFORM_LONG_LABELS[cycle.platform]}: свежесть сбора`} value={age == null ? null : Math.min(100, age * 100 / cycle.freshnessSeconds)} />
      <p className="text-muted-foreground mb-3 text-xs">норма — до {duration(cycle.freshnessSeconds)}</p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <Fact label="Циклов за период">{number.format(cycle.runs)}{cycle.failed ? <span className="text-destructive"> · {cycle.failed} сбой ({failedShare}%)</span> : null}</Fact>
        <Fact label="Аккаунтов опрошено">{number.format(cycle.accounts)}{cycle.errors ? <span className="text-warning"> · {number.format(cycle.errors)} ош.</span> : null}</Fact>
        <Fact label="Длительность цикла">{duration(cycle.cycleSeconds ?? cycle.medianSeconds)}<span className="text-muted-foreground text-xs"> · медиана {duration(cycle.medianSeconds)}</span></Fact>
        <Fact label="Отставание от расписания" tone={(cycle.scheduleLagSeconds ?? 0) > 300 ? "text-warning" : undefined}>{duration(cycle.scheduleLagSeconds)}</Fact>
      </dl>
      <div className="mt-3 border-t pt-2">
        <GapList gaps={cycle.gaps} what="сбора" compact />
      </div>
    </article>
  );
}

/** Процессы сервера-сборщика для вкладки «Система»: не нагрузка машины, а
 *  его собственная работа — циклы площадок, отправка пачек, задания узла. */
export function CollectorProcesses({ overview, now, href }: { overview: CollectorsOverview | null; now: number; href: (id: string) => string }) {
  if (!overview) return <p className="text-destructive">Не удалось получить процессы сборщиков.</p>;
  if (!overview.collectors.length) return <p className="text-muted-foreground">Подключённых серверов-сборщиков нет.</p>;
  const selected = overview.selected;
  return <>
    <ServerSwitch servers={overview.collectors} selected={selected?.server.id ?? null} href={href} label="Сервер-сборщик" now={now} />
    {selected ? <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-testid="collector-cycles">
        {selected.cycles.map((cycle) => <Cycle key={cycle.platform} cycle={cycle} now={now} />)}
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div className="min-w-0 rounded-lg border p-4" data-testid="collector-transfer">
          <p className="mb-3 flex items-center gap-2 font-medium"><ArrowUpFromLine className="size-4" aria-hidden="true" />Отправка пачек на Сервер 2</p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <Fact label="В очереди" tone={(selected.transfer.backlog ?? 0) > 50 ? "text-warning" : undefined}>
              {selected.transfer.backlog == null ? "—" : `${number.format(selected.transfer.backlog)} ${plural(selected.transfer.backlog, "пачка", "пачки", "пачек")}`}</Fact>
            <Fact label="Задержка очереди">{duration(selected.transfer.queueDelaySeconds)}</Fact>
            <Fact label="Последний приём">{ago(selected.transfer.lastAcceptedAt, now)}</Fact>
            <Fact label="Доставлено · сбоев" tone={selected.transfer.failures ? "text-warning" : undefined}>
              {selected.transfer.delivered == null ? "—" : number.format(selected.transfer.delivered)} · {number.format(selected.transfer.failures ?? 0)}</Fact>
          </dl>
          <p className="text-muted-foreground mt-3 text-xs">Счётчики отправителя — с его последнего запуска; задержка — от запечатывания пачки до приёма.</p>
        </div>
        <div className="min-w-0 rounded-lg border p-4">
          <p className="mb-2 font-medium">Службы и задания сборщика</p>
          <TaskList tasks={selected.tasks} now={now} />
        </div>
      </div>
    </> : null}
  </>;
}
