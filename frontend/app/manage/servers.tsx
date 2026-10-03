import type * as React from "react";
import { Archive, HardDrive, Play, Plus, RefreshCw, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { StorageOverview } from "@/lib/catalog-api";
import { PLATFORM_LONG_LABELS } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ago, bytes, fields, Pill, Section } from "./shared";

type Server = StorageOverview["servers"][number];
type Replica = StorageOverview["backups"][number]["replicas"][number];
type Month = StorageOverview["archive"][number];
type Platform = Server["platforms"][number];

const PLATFORMS: Platform[] = ["telegram", "vk", "max", "rutube"];
const number = new Intl.NumberFormat("ru-RU");
const ROLE: Record<Server["role"], string> = { main: "основной", collector: "сборщик", storage: "хранение" };
const STATE: Record<Server["state"], [string, string]> = {
  active: ["подключён", "text-success"], pending: ["ожидает", "text-muted-foreground"],
  draining: ["выводится", "text-warning"], disabled: ["отключён", "text-muted-foreground"],
};
const REPLICA: Record<Replica["state"], [string, string]> = {
  verified: ["сверена", "text-success"], wanted: ["в очереди", "text-muted-foreground"],
  transferring: ["копируется", "text-warning"], deleting: ["удаляется", "text-muted-foreground"],
  deleted: ["удалена", "text-muted-foreground"], failed: ["сбой", "text-destructive"],
};
const GENERATION: Record<Month["generations"][number]["state"], string> = {
  preparing: "готовится", exporting: "выгружается", replicating: "копируется на второй сервер",
  dropping: "удаляется из базы", cold: "в архиве", failed: "не удалось",
};
const STATUS: Record<string, string> = {
  "server-added": "Сервер добавлен. Приём с него откроется в течение 30 секунд, агент получит состав сборщиков в течение минуты.",
  "server-updated": "Настройки сервера сохранены.",
  "policy-collection": "Политика сбора сохранена: сборщики применят её с ближайшего цикла.",
  "policy-storage": "Политика хранения сохранена: размещение копий пересчитается в течение минуты.",
  "policy-analysis": "Политика анализа сохранена: анализ применит её в течение минуты.",
  "job-queued": "Задание поставлено в очередь и начнётся в течение минуты.",
};
const ERROR: Record<string, string> = {
  "server-id": "Имя сервера: латиница в нижнем регистре, цифры и дефис, 2–40 символов, начинается с буквы. Оно должно совпадать с именем в сертификате сервера.",
  "server-name": "Укажите название сервера (до 80 символов).", "server-role": "Выберите роль сервера.",
  "server-state": "Такое состояние для этого сервера недоступно.", "server-platforms": "Площадки назначаются только серверу-сборщику.",
  "server-reserve": "Запас места — целое число гигабайт от 0 до 1000.", "server-exists": "Сервер с таким именем уже есть.",
  "server-missing": "Сервер не найден.", "policy-collection": "Проверьте значения политики сбора: целые числа в указанных пределах.",
  "policy-cold-days": "Срок горячего хранения — от 30 до 3650 дней.", "policy-backup-copies": "Число резервных копий — от 1 до 14.",
  "policy-backup-nodes": "Выберите хотя бы один сервер для резервных копий.",
  "policy-archive-nodes": "Полный архив хранится минимум на двух серверах: после удаления месяца из базы это единственные его копии.",
  "policy-cold-before-analysis": "Финальный анализ должен проходить не позже ухода месяца в архив: срок анализа не больше срока горячего хранения.",
  "policy-analysis": "Срок финального анализа — от 3 до 3650 дней или пусто.", "policy-storage": "Политика хранения не прошла проверку.",
  "archive-month": "Месяц указывается в виде ГГГГ-ММ.", "archive-platform": "Неизвестная площадка.",
  "job-busy": "Такое задание уже стоит в очереди или выполняется.", unknown: "Неизвестная команда.",
};

function percent(part: number | null, total: number | null) {
  return part != null && total ? Math.min(100, Math.round(part * 100 / total)) : null;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <Label className="grid min-w-0 gap-1.5 text-sm leading-normal font-normal">
    <span>{label}</span>{children}{hint ? <span className="text-muted-foreground text-xs">{hint}</span> : null}
  </Label>;
}

function Check({ name, label, checked, disabled }: { name: string; label: string; checked: boolean; disabled?: boolean }) {
  return <label className="inline-flex items-center gap-2 text-sm">
    <input type="checkbox" name={name} defaultChecked={checked} disabled={disabled} className="accent-primary size-4" />{label}
  </label>;
}

function Disk({ server }: { server: Server }) {
  const { totalBytes: total, freeBytes: free } = server.disk;
  const used = total != null && free != null ? total - free : null;
  const share = percent(used, total);
  const low = free != null && free < server.reserveBytes;
  return <div>
    <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
      <span className="text-muted-foreground">Диск</span>
      <b className={cn("tabular-nums", low && "text-destructive")}>{bytes(free)} свободно из {bytes(total)}</b>
    </div>
    <Progress className="my-2 [&_[data-slot=progress-track]]:h-2 [&_[data-slot=progress-track]]:rounded-full" aria-label={`Диск ${server.displayName}`} value={share} />
    <p className="text-muted-foreground text-xs">
      {share == null ? "Агент ещё не прислал отчёт" : `занято ${share}%`} · хранилище {bytes(server.disk.storeBytes)} · запас {bytes(server.reserveBytes)}
      {low ? " · меньше запаса: новые копии сюда не пойдут" : ""}
    </p>
  </div>;
}

function ServerForm({ server, csrf, canEdit }: { server: Server; csrf: string; canEdit: boolean }) {
  const states: Server["state"][] = server.role === "main" ? ["active"] : ["active", "pending", "draining", "disabled"];
  return <details className="mt-4 border-t pt-3">
    <summary className="cursor-pointer text-sm font-medium">Настроить</summary>
    <form method="post" action={`/manage/servers/${server.id}`} className="mt-3 grid gap-3">
      {fields(csrf)}
      <Field label="Название"><Input name="display_name" defaultValue={server.displayName} maxLength={80} required disabled={!canEdit} /></Field>
      <Field label="Состояние" hint="«Выводится» — новые копии не принимает, сбор отдаёт другим; «отключён» — приём с сервера закрыт.">
        <NativeSelect name="state" defaultValue={server.state} className="w-full" disabled={!canEdit}>
          {states.map((state) => <NativeSelectOption key={state} value={state}>{STATE[state][0]}</NativeSelectOption>)}
        </NativeSelect>
      </Field>
      {server.role === "collector" ? <fieldset className="grid gap-2"><legend className="mb-1 text-sm">Площадки сбора</legend>
        <div className="flex flex-wrap gap-4">{PLATFORMS.map((platform) => <Check key={platform} name={`platform_${platform}`} label={PLATFORM_LONG_LABELS[platform]} checked={server.platforms.includes(platform)} disabled={!canEdit} />)}</div>
      </fieldset> : null}
      <Check name="stores_objects" label="Хранит резервные копии и архив" checked={server.storesObjects} disabled={!canEdit} />
      <Field label="Запас свободного места, ГБ" hint="Копия не ляжет на сервер, если после неё останется меньше.">
        <Input name="reserve_gb" type="number" min={0} max={1000} defaultValue={Math.round(server.reserveBytes / 1024 ** 3)} required disabled={!canEdit} />
      </Field>
      <div><Button type="submit" disabled={!canEdit}><Save data-icon="inline-start" aria-hidden="true" />Сохранить</Button></div>
    </form>
  </details>;
}

function Servers({ servers, csrf, canEdit, now }: { servers: Server[]; csrf: string; canEdit: boolean; now: number }) {
  return <Section title="Серверы" description="Каждый сервер раз в минуту присылает отчёт агента: диск, память, службы и файлы хранилища. Сервер без отчёта дольше трёх минут считается не на связи.">
    <div className="grid gap-4 lg:grid-cols-2" data-testid="storage-servers">
      {servers.map((server) => {
        const [stateLabel, stateTone] = STATE[server.state];
        const units = Object.entries(server.units);
        const failed = units.filter(([, state]) => state !== "active");
        const verified = server.copies.verified;
        return <article key={server.id} data-server={server.id} className="min-w-0 rounded-lg border p-4">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <h3 className="font-medium"><HardDrive className="mr-1.5 inline size-4" aria-hidden="true" />{server.displayName}</h3>
              <p className="text-muted-foreground font-mono text-xs">{server.id} · {ROLE[server.role]}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Pill className={stateTone}>{stateLabel}</Pill>
              <Pill className={server.online ? "text-success" : "text-destructive"}>{server.online ? "на связи" : server.lastSeenAt ? `нет связи · ${ago(server.lastSeenAt, now)}` : "агент не отвечал"}</Pill>
            </div>
          </div>
          <Disk server={server} />
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <dt className="text-muted-foreground">Память</dt>
            <dd className="text-right tabular-nums">{server.memory.availableBytes == null ? "—" : `${bytes(server.memory.availableBytes)} свободно из ${bytes(server.memory.totalBytes)}`}</dd>
            <dt className="text-muted-foreground">Нагрузка</dt>
            <dd className="text-right tabular-nums">{server.load1 == null ? "—" : `${server.load1.toFixed(2)} на ${server.cpus ?? "—"} ядр.`}</dd>
            <dt className="text-muted-foreground">Площадки</dt>
            <dd className="text-right">{server.platforms.length ? server.platforms.map((platform) => PLATFORM_LONG_LABELS[platform]).join(", ") : "—"}</dd>
            <dt className="text-muted-foreground">Сверенных копий</dt>
            <dd className="text-right tabular-nums">{verified ? `${number.format(verified.objects)} · ${bytes(verified.bytes)}` : "нет"}</dd>
            <dt className="text-muted-foreground">Службы</dt>
            <dd className={cn("text-right", failed.length && "text-destructive")}>{units.length ? failed.length ? `не работают: ${failed.map(([unit]) => unit.replace(/\.service$/, "")).join(", ")}` : `${units.length} работают` : "—"}</dd>
          </dl>
          <ServerForm server={server} csrf={csrf} canEdit={canEdit} />
        </article>;
      })}
    </div>
  </Section>;
}

function AddServer({ csrf, canEdit }: { csrf: string; canEdit: boolean }) {
  return <Section title="Подключить сервер" description={<>Сервер должен быть подготовлен заранее: установлены сборщик и агент узла, выпущен mTLS-сертификат отправителя. Имя ниже — то же, что в сертификате. После сохранения приёмник начинает принимать с него данные в течение 30 секунд, а сборщики делят аккаунты выбранных площадок с учётом нового участника со следующего цикла — без перезапуска служб.</>}>
    <form method="post" action="/manage/servers" className="grid gap-3 md:grid-cols-2">
      {fields(csrf)}
      <Field label="Имя (как в сертификате)" hint="Например, server-3."><Input name="id" pattern="[a-z][a-z0-9-]{1,39}" maxLength={40} required disabled={!canEdit} spellCheck={false} autoComplete="off" /></Field>
      <Field label="Название"><Input name="display_name" maxLength={80} required disabled={!canEdit} placeholder="Сервер 3 · сбор" /></Field>
      <Field label="Роль">
        <NativeSelect name="role" defaultValue="collector" className="w-full" disabled={!canEdit}>
          <NativeSelectOption value="collector">Сборщик</NativeSelectOption>
          <NativeSelectOption value="storage">Только хранение</NativeSelectOption>
        </NativeSelect>
      </Field>
      <Field label="Состояние после добавления">
        <NativeSelect name="state" defaultValue="active" className="w-full" disabled={!canEdit}>
          <NativeSelectOption value="active">Подключить сразу</NativeSelectOption>
          <NativeSelectOption value="pending">Добавить, подключу позже</NativeSelectOption>
        </NativeSelect>
      </Field>
      <fieldset className="grid gap-2 md:col-span-2"><legend className="mb-1 text-sm">Площадки сбора (для сборщика)</legend>
        <div className="flex flex-wrap gap-4">{PLATFORMS.map((platform) => <Check key={platform} name={`platform_${platform}`} label={PLATFORM_LONG_LABELS[platform]} checked={false} disabled={!canEdit} />)}</div>
      </fieldset>
      <Check name="stores_objects" label="Хранит резервные копии и архив" checked disabled={!canEdit} />
      <Field label="Запас свободного места, ГБ"><Input name="reserve_gb" type="number" min={0} max={1000} defaultValue={3} required disabled={!canEdit} /></Field>
      <div className="md:col-span-2"><Button type="submit" disabled={!canEdit}><Plus data-icon="inline-start" aria-hidden="true" />Добавить сервер</Button></div>
    </form>
  </Section>;
}

function policyValue(overview: StorageOverview, name: string): Record<string, unknown> {
  return (overview.policies[name]?.value ?? {}) as Record<string, unknown>;
}

function Updated({ overview, name, now }: { overview: StorageOverview; name: string; now: number }) {
  const policy = overview.policies[name];
  return policy?.updatedBy ? <p className="text-muted-foreground mt-3 text-xs">Изменена {ago(policy.updatedAt, now)} · {policy.updatedBy} · версия {policy.version}</p> : null;
}

function StoragePolicy({ overview, csrf, canEdit, now }: { overview: StorageOverview; csrf: string; canEdit: boolean; now: number }) {
  const value = policyValue(overview, "storage");
  const backupNodes = (value.backupNodes as string[] | undefined) ?? [];
  const archiveNodes = (value.archiveNodes as string[] | undefined) ?? [];
  const candidates = overview.servers.filter((server) => server.storesObjects && server.state !== "disabled");
  return <Section title="Политика хранения" description="Замеры месяца публикации уходят в холодный архив, когда со дня конца месяца прошёл срок горячего хранения. Архив месяца — два файла: полный Parquet для восстановления (на выбранных серверах) и компактный файл просмотра (всегда на основном сервере), из которого пост открывается за миллисекунды.">
    <form method="post" action="/manage/policies/storage" className="grid gap-4 md:grid-cols-2">
      {fields(csrf)}
      <Field label="Горячее хранение, дней после конца месяца" hint="От 30. Пример: 30 — замеры постов сентября уходят в архив 31 октября.">
        <Input name="coldAfterDays" type="number" min={30} max={3650} defaultValue={Number(value.coldAfterDays ?? 30)} required disabled={!canEdit} />
      </Field>
      <Field label="Хранить резервных копий базы" hint="Более старые выводятся, когда у новых есть сверенные копии.">
        <Input name="backupCopies" type="number" min={1} max={14} defaultValue={Number(value.backupCopies ?? 1)} required disabled={!canEdit} />
      </Field>
      <fieldset className="grid gap-2"><legend className="mb-1 text-sm">Резервные копии хранятся на</legend>
        {candidates.map((server) => <Check key={server.id} name={`backup_${server.id}`} label={server.displayName} checked={backupNodes.includes(server.id)} disabled={!canEdit} />)}
      </fieldset>
      <fieldset className="grid gap-2"><legend className="mb-1 text-sm">Полный архив хранится на (минимум два)</legend>
        {candidates.map((server) => <Check key={server.id} name={`archive_${server.id}`} label={server.displayName} checked={archiveNodes.includes(server.id)} disabled={!canEdit} />)}
      </fieldset>
      <div className="md:col-span-2"><Button type="submit" disabled={!canEdit}><Save data-icon="inline-start" aria-hidden="true" />Сохранить и переразместить</Button>
        <p className="text-muted-foreground mt-2 text-xs">Файлы переезжают сами: агенты копируют их по 8 МБ с докачкой и сверкой SHA-256, а старая копия удаляется только после сверки всех новых.</p>
      </div>
    </form>
    <Updated overview={overview} name="storage" now={now} />
  </Section>;
}

function AnalysisPolicy({ overview, csrf, canEdit, now }: { overview: StorageOverview; csrf: string; canEdit: boolean; now: number }) {
  const value = policyValue(overview, "analysis");
  const [low, high] = overview.limits.finalAnalysisDays;
  return <Section title="Политика анализа" description="Пост анализируется, пока не достигнет срока финального анализа: тогда он проходит последний анализ по всему ряду и замораживается. Месяц уходит в архив только после финального анализа всех его постов.">
    <form method="post" action="/manage/policies/analysis" className="grid gap-3 md:grid-cols-2">
      {fields(csrf)}
      <Field label="Финальный анализ на возрасте поста, дней" hint="Пусто — как в окружении службы анализа (обычно 30). Не больше срока горячего хранения.">
        <Input name="finalAnalysisDays" type="number" min={low} max={high} defaultValue={value.finalAnalysisDays == null ? "" : Number(value.finalAnalysisDays)} disabled={!canEdit} />
      </Field>
      <div className="self-end"><Button type="submit" disabled={!canEdit}><Save data-icon="inline-start" aria-hidden="true" />Сохранить</Button></div>
    </form>
    <Updated overview={overview} name="analysis" now={now} />
  </Section>;
}

const COLLECTION_LABELS: Record<string, string> = {
  trackPostDays: "Следить за постом, дней", snapshotHeartbeatHours: "Контрольный замер без изменений, раз в N часов",
  pollIntervalMinutes: "Опрос в первые сутки, мин", secondDayPollIntervalMinutes: "Опрос на вторые сутки, мин",
  thirdDayPollIntervalMinutes: "Опрос на третьи сутки, мин", days4To6PollIntervalMinutes: "Опрос на 4–6 сутки, мин",
  days7To13PollIntervalMinutes: "Опрос на 7–13 сутки, мин", day14PlusPollIntervalMinutes: "Опрос с 14 суток, мин",
  refreshLimit: "Постов на обновление за цикл",
};

function CollectionPolicy({ overview, csrf, canEdit, now }: { overview: StorageOverview; csrf: string; canEdit: boolean; now: number }) {
  const value = policyValue(overview, "collection");
  return <Section title="Политика сбора" description="Действует на всех сборщиках со следующего цикла, без перезапуска. Пустое поле — значение из окружения сборщика.">
    <form method="post" action="/manage/policies/collection" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {fields(csrf)}
      {Object.entries(overview.limits.collection).map(([key, [low, high]]) => (
        <Field key={key} label={COLLECTION_LABELS[key] ?? key} hint={`${low}–${high}`}>
          <Input name={key} type="number" min={low} max={high} defaultValue={value[key] == null ? "" : Number(value[key])} disabled={!canEdit} />
        </Field>
      ))}
      <Field label="Контрольные замеры до возраста, дней" hint="Пусто — без ограничения.">
        <Input name="heartbeatMaxAgeDays" type="number" min={1} max={3650} defaultValue={value.heartbeatMaxAgeDays == null ? "" : Number(value.heartbeatMaxAgeDays)} disabled={!canEdit} />
      </Field>
      <div className="sm:col-span-2 lg:col-span-3"><Button type="submit" disabled={!canEdit}><Save data-icon="inline-start" aria-hidden="true" />Сохранить</Button></div>
    </form>
    <Updated overview={overview} name="collection" now={now} />
  </Section>;
}

function Replicas({ replicas, servers }: { replicas: Replica[]; servers: Map<string, string> }) {
  if (!replicas.length) return <span className="text-muted-foreground">—</span>;
  return <span className="flex flex-wrap gap-1.5">{replicas.map((replica) => {
    const [label, tone] = REPLICA[replica.state];
    return <span key={replica.node} className={cn("text-xs", tone)} title={replica.error ?? undefined}>{servers.get(replica.node) ?? replica.node}: {label}</span>;
  })}</span>;
}

function Backups({ overview, servers, now }: { overview: StorageOverview; servers: Map<string, string>; now: number }) {
  return <Section title="Резервные копии по серверам" description="Законченный снимок базы попадает в хранилище основного сервера в течение минуты и копируется на серверы из политики хранения.">
    {overview.backups.length ? <div className="overflow-x-auto"><Table>
      <TableHeader><TableRow><TableHead>Снимок</TableHead><TableHead className="text-right">Размер</TableHead><TableHead>Снят</TableHead><TableHead>Копии</TableHead></TableRow></TableHeader>
      <TableBody>{overview.backups.map((backup) => <TableRow key={backup.id} className={backup.retired ? "opacity-60" : undefined}>
        <TableCell className="font-mono text-xs">{backup.name}{backup.retired ? " · выведена" : ""}</TableCell>
        <TableCell className="text-right tabular-nums">{bytes(backup.sizeBytes)}</TableCell>
        <TableCell>{ago(backup.createdAt, now)}</TableCell>
        <TableCell><Replicas replicas={backup.replicas} servers={servers} /></TableCell>
      </TableRow>)}</TableBody>
    </Table></div> : <p className="text-muted-foreground">Резервных копий в хранилище пока нет: агент основного сервера зарегистрирует ближайший снимок.</p>}
  </Section>;
}

function ArchiveMonths({ overview, servers, csrf, canEdit, now }: { overview: StorageOverview; servers: Map<string, string>; csrf: string; canEdit: boolean; now: number }) {
  const today = new Date(now).toISOString().slice(0, 10);
  return <Section title="Холодный архив" description="Месяцы — по дате публикации постов. Пока месяц выгружается, запись в него закрыта (не дольше двух часов): поздние замеры с Сервера 1 ждут и не теряются. После удаления из базы месяц снова открыт, а поздние контрольные замеры уйдут в архив следующим поколением."
    action={<form method="post" action="/manage/archive/run">{fields(csrf)}
      <Button type="submit" variant="outline" disabled={!canEdit}><Play data-icon="inline-start" aria-hidden="true" />Архивировать созревшие</Button>
    </form>}>
    <div className="overflow-x-auto"><Table>
      <TableHeader><TableRow><TableHead>Месяц</TableHead><TableHead className="text-right">В базе</TableHead><TableHead>Архив</TableHead><TableHead>Действия</TableHead></TableRow></TableHeader>
      <TableBody>{overview.archive.map((month) => {
        const cold = month.generations.filter((item) => item.state === "cold");
        const due = month.coldFrom <= today;
        return <TableRow key={month.month} data-month={month.month}>
          <TableCell className="align-top font-medium tabular-nums">{month.month}{month.fence !== "active" ? <span className="text-warning block text-xs">запись закрыта на выгрузку</span> : null}</TableCell>
          <TableCell className="text-right align-top tabular-nums">{bytes(month.hotBytes)}<span className="text-muted-foreground block text-xs">{due ? "созрел для архива" : `в архив с ${month.coldFrom}`}</span></TableCell>
          <TableCell className="align-top">{month.generations.length ? <ul className="grid gap-2">{month.generations.map((generation) => (
            <li key={generation.generation} className="text-xs">
              <b>Поколение {generation.generation}</b> · <span className={generation.state === "failed" ? "text-destructive" : generation.state === "cold" ? "text-success" : "text-warning"}>{GENERATION[generation.state]}</span>
              {generation.rowCount != null ? ` · ${number.format(generation.rowCount)} замеров, ${number.format(generation.publications ?? 0)} постов` : ""}
              {generation.full ? <span className="block">полный {bytes(generation.full.sizeBytes)} (было в базе {bytes(generation.hotBytes)}): <Replicas replicas={generation.full.replicas} servers={servers} /></span> : null}
              {generation.browse ? <span className="block">просмотр {bytes(generation.browse.sizeBytes)}: <Replicas replicas={generation.browse.replicas} servers={servers} /></span> : null}
              {generation.error ? <span className="text-destructive block">{generation.error}</span> : null}
            </li>))}</ul> : <span className="text-muted-foreground text-xs">не архивировался</span>}</TableCell>
          <TableCell className="align-top">
            <div className="flex flex-wrap gap-2">
              {due && month.hotBytes ? <form method="post" action="/manage/archive/run">{fields(csrf)}<input type="hidden" name="month" value={month.month} />
                <Button type="submit" size="sm" variant="outline" disabled={!canEdit}><Archive data-icon="inline-start" aria-hidden="true" />В архив</Button></form> : null}
              {cold.length ? <form method="post" action="/manage/archive/analysis">{fields(csrf)}<input type="hidden" name="month" value={month.month} />
                <Button type="submit" size="sm" variant="outline" disabled={!canEdit} title="Финальный анализ всех постов месяца заново — по данным архива и текущими детекторами">
                  <RefreshCw data-icon="inline-start" aria-hidden="true" />Анализ заново</Button></form> : null}
            </div>
          </TableCell>
        </TableRow>;
      })}</TableBody>
    </Table></div>
  </Section>;
}

const JOB_KIND: Record<string, string> = { archive_now: "Архивация", archive_analysis: "Анализ архива" };
const JOB_STATE: Record<string, [string, string]> = {
  queued: ["в очереди", "text-muted-foreground"], running: ["выполняется", "text-warning"], done: ["готово", "text-success"],
  failed: ["ошибка", "text-destructive"], cancelled: ["отменено", "text-muted-foreground"],
};

function Jobs({ overview, now }: { overview: StorageOverview; now: number }) {
  if (!overview.jobs.length) return null;
  return <Section title="Задания">
    <ul className="divide-y rounded-lg border text-sm">{overview.jobs.map((job) => {
      const [label, tone] = JOB_STATE[job.state] ?? [job.state, ""];
      const params = job.params as { month?: string; platform?: string };
      const result = job.result as { status?: string; month?: string; publications?: number; queued?: number } | null;
      return <li key={job.id} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-2.5">
        <span>{JOB_KIND[job.kind] ?? job.kind}{params.month ? ` · ${params.month}` : ""}{params.platform ? ` · ${PLATFORM_LONG_LABELS[params.platform as Platform] ?? params.platform}` : ""}</span>
        <span className="text-muted-foreground text-xs">
          <span className={tone}>{label}</span> · {job.requestedBy} · {ago(job.requestedAt, now)}
          {result?.queued != null ? ` · поставлено на анализ ${number.format(result.queued)}` : ""}
          {result?.status === "idle" ? " · созревших месяцев нет" : result?.status === "cold" ? ` · ${result.month} в архиве` : ""}
          {job.error ? <span className="text-destructive"> · {job.error}</span> : null}
        </span>
      </li>;
    })}</ul>
  </Section>;
}

export function ServersTab({ overview, csrf, canEdit, now, status, error }: {
  overview: StorageOverview | null; csrf: string; canEdit: boolean; now: number; status?: string; error?: string;
}) {
  if (!overview) return <Section title="Серверы"><p className="text-destructive">Не удалось получить состояние серверов и хранилища.</p></Section>;
  const servers = new Map(overview.servers.map((server) => [server.id, server.displayName]));
  return <>
    {status && STATUS[status] ? <p role="status" className="text-success mb-4 text-sm">{STATUS[status]}</p> : null}
    {error ? <p role="alert" className="text-destructive mb-4 text-sm">{ERROR[error] ?? "Не удалось сохранить изменение."}</p> : null}
    {!canEdit ? <p className="text-muted-foreground mb-4 text-sm">Изменять серверы и политики может роль ADMIN.</p> : null}
    <Servers servers={overview.servers} csrf={csrf} canEdit={canEdit} now={now} />
    <AddServer csrf={csrf} canEdit={canEdit} />
    <div className="grid gap-x-5 xl:grid-cols-2">
      <StoragePolicy overview={overview} csrf={csrf} canEdit={canEdit} now={now} />
      <AnalysisPolicy overview={overview} csrf={csrf} canEdit={canEdit} now={now} />
    </div>
    <CollectionPolicy overview={overview} csrf={csrf} canEdit={canEdit} now={now} />
    <ArchiveMonths overview={overview} servers={servers} csrf={csrf} canEdit={canEdit} now={now} />
    <Backups overview={overview} servers={servers} now={now} />
    <Jobs overview={overview} now={now} />
  </>;
}
