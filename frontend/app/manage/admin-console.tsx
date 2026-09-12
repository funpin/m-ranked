"use client";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { NativeButton } from "@/components/native-field";
import { NativeSelect } from "@/components/native-field";
import { NativeInput as Input } from "@/components/native-field";

import { type FormEvent, useEffect, useRef, useState } from "react";
import { PageHeader, StatusPill } from "@/components/ui";
import {
  ADMIN_JOB_STATUSES,
  ADMIN_PLATFORMS,
  AdminApiError,
  type AdminJob,
  type AdminJobDetail,
  type AdminJobStatus,
  type AdminPlatform,
  type AdminSession,
  createAdminSession,
  type PlatformAccountAdminState,
  type SetEnabledResponse,
  withConflictRefresh,
} from "@/lib/admin-api";


const PLATFORM_LABELS: Record<AdminPlatform, string> = {
  "": "Все площадки",
  telegram: "Telegram",
  vk: "ВКонтакте",
  max: "MAX",
  rutube: "Rutube",
};

const STATUS_LABELS: Record<AdminJobStatus, string> = {
  "": "Все статусы",
  pending: "Ожидает",
  running: "Выполняется",
  succeeded: "Завершён",
  partial: "Частично",
  failed: "Ошибка",
  skipped: "Пропущен",
  cancelled: "Отменён",
};

function statusTone(status: string): "green" | "amber" | "red" | "blue" | "neutral" {
  if (status === "succeeded") return "green";
  if (status === "failed" || status === "cancelled") return "red";
  if (status === "partial" || status === "skipped") return "amber";
  if (status === "running") return "blue";
  return "neutral";
}

function dateTime(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "medium",
    timeZone: "Europe/Moscow",
  }).format(parsed);
}

function messageFor(error: unknown, action: "read" | "write" = "read"): string {
  if (!(error instanceof AdminApiError)) return "Не удалось выполнить административный запрос.";
  if (error.status === 0) return error.message;
  if (error.status === 401) return "Неверное имя пользователя или пароль. Сессия завершена.";
  if (error.status === 403) {
    return action === "write"
      ? "Запись запрещена: нужна роль editor/admin и действующий CSRF-токен."
      : "У этой учётной записи нет доступа к административным данным.";
  }
  if (error.status === 409) {
    return "Аккаунт уже изменён другим оператором. Актуальное состояние загружено; проверьте его и подтвердите действие снова.";
  }
  if (error.status === 404) return "Запрашиваемый запуск или аккаунт не найден.";
  if (error.status === 503) return "Административная база временно недоступна; изменение не выполнено.";
  return error.message;
}

interface MutationDraft {
  accountId: string;
  enabled: boolean;
  expectedRowVersion: number;
}

export function AdminConsole() {
  const sessionRef = useRef<AdminSession | null>(null);
  const mutationAccountRef = useRef<HTMLInputElement | null>(null);
  const accountRequestSequence = useRef(0);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authenticated, setAuthenticated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [platform, setPlatform] = useState<AdminPlatform>("");
  const [status, setStatus] = useState<AdminJobStatus>("");
  const [limit, setLimit] = useState(50);
  const [jobs, setJobs] = useState<AdminJob[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [jobDetail, setJobDetail] = useState<AdminJobDetail | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const [accountId, setAccountId] = useState("");
  const [accountState, setAccountState] = useState<PlatformAccountAdminState | null>(null);
  const [accountBusy, setAccountBusy] = useState(false);
  const [desiredEnabled, setDesiredEnabled] = useState(true);
  const [pendingMutation, setPendingMutation] = useState<MutationDraft | null>(null);
  const [mutationResult, setMutationResult] = useState<SetEnabledResponse | null>(null);

  function clearPrivateState(message?: string) {
    sessionRef.current?.close();
    sessionRef.current = null;
    setUsername("");
    setPassword("");
    setAuthenticated(false);
    setJobs([]);
    setSelectedJobId(null);
    setJobDetail(null);
    setAccountId("");
    setAccountState(null);
    setAccountBusy(false);
    accountRequestSequence.current += 1;
    setPendingMutation(null);
    setMutationResult(null);
    setNotice(message ?? null);
  }

  useEffect(() => {
    const purge = () => {
      sessionRef.current?.close();
      sessionRef.current = null;
    };
    window.addEventListener("pagehide", purge);
    return () => {
      window.removeEventListener("pagehide", purge);
      purge();
    };
  }, []);

  async function fetchJobs(session: AdminSession = sessionRef.current!): Promise<void> {
    const page = await session.jobs({ platform, status, limit });
    setJobs(page.items);
  }

  async function refreshVisibleData(): Promise<void> {
    const session = sessionRef.current;
    if (!session) return;
    if (accountId.trim()) {
      try {
        setAccountState(await session.account(accountId));
      } catch (refreshError) {
        if (refreshError instanceof AdminApiError && refreshError.status === 404) {
          setAccountState(null);
        } else {
          throw refreshError;
        }
      }
    }
    await fetchJobs(session);
    if (selectedJobId) {
      try {
        setJobDetail(await session.job(selectedJobId));
      } catch (refreshError) {
        if (refreshError instanceof AdminApiError && refreshError.status === 404) {
          setSelectedJobId(null);
          setJobDetail(null);
          return;
        }
        throw refreshError;
      }
    }
  }

  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    let session: AdminSession | null = null;
    try {
      session = createAdminSession({ username, password });
      await session.initialize();
      const page = await session.jobs({ platform, status, limit });
      sessionRef.current?.close();
      sessionRef.current = session;
      setJobs(page.items);
      setAuthenticated(true);
      setNotice("Административная сессия открыта только в памяти этой страницы.");
    } catch (authError) {
      session?.close();
      setError(messageFor(authError));
      setAuthenticated(false);
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  async function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const session = sessionRef.current;
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      await fetchJobs(session);
    } catch (jobsError) {
      if (jobsError instanceof AdminApiError && jobsError.status === 401) {
        clearPrivateState();
      }
      setError(messageFor(jobsError));
    } finally {
      setBusy(false);
    }
  }

  async function inspectJob(jobId: string) {
    const session = sessionRef.current;
    if (!session) return;
    setDetailBusy(true);
    setError(null);
    setSelectedJobId(jobId);
    try {
      setJobDetail(await session.job(jobId));
    } catch (jobError) {
      setJobDetail(null);
      if (jobError instanceof AdminApiError && jobError.status === 401) clearPrivateState();
      setError(messageFor(jobError));
    } finally {
      setDetailBusy(false);
    }
  }

  function clearLoadedAccount(id: string) {
    setAccountId(id);
    setAccountState(null);
    setAccountBusy(false);
    setPendingMutation(null);
    setMutationResult(null);
    accountRequestSequence.current += 1;
  }

  async function loadAccountState(id: string, announce = true) {
    const session = sessionRef.current;
    if (!session) return;
    const sequence = accountRequestSequence.current + 1;
    accountRequestSequence.current = sequence;
    setAccountBusy(true);
    setError(null);
    setNotice(null);
    setPendingMutation(null);
    setMutationResult(null);
    try {
      const loaded = await session.account(id);
      if (accountRequestSequence.current !== sequence) return;
      setAccountId(loaded.accountId);
      setAccountState(loaded);
      if (announce) setNotice("Актуальное состояние аккаунта загружено из административной базы.");
    } catch (accountError) {
      if (accountRequestSequence.current !== sequence) return;
      setAccountState(null);
      if (accountError instanceof AdminApiError && accountError.status === 401) clearPrivateState();
      setError(messageFor(accountError));
    } finally {
      if (accountRequestSequence.current === sequence) setAccountBusy(false);
    }
  }

  async function lookupAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await loadAccountState(accountId);
  }

  async function selectAccount(id: string) {
    clearLoadedAccount(id);
    requestAnimationFrame(() => mutationAccountRef.current?.focus());
    await loadAccountState(id);
  }

  function prepareMutation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setMutationResult(null);
    if (!accountId.trim()) {
      setError("Укажите UUID платформенного аккаунта.");
      return;
    }
    if (!accountState || accountState.accountId !== accountId.trim().toLowerCase()) {
      setError("Сначала загрузите актуальное состояние этого аккаунта.");
      return;
    }
    setPendingMutation({
      accountId: accountState.accountId,
      enabled: desiredEnabled,
      expectedRowVersion: accountState.rowVersion,
    });
  }

  async function confirmMutation() {
    const session = sessionRef.current;
    const draft = pendingMutation;
    if (!session || !draft) return;
    setBusy(true);
    setError(null);
    try {
      const result = await withConflictRefresh(
        () => session.setAccountEnabled(draft),
        refreshVisibleData,
      );
      setMutationResult(result);
      setAccountState(result.account);
      setNotice(result.changed
        ? `Состояние аккаунта изменено. Correlation ID: ${result.correlationId}`
        : `Состояние уже соответствовало запросу. Correlation ID: ${result.correlationId}`);
    } catch (mutationError) {
      if (mutationError instanceof AdminApiError && mutationError.status === 401) {
        clearPrivateState();
      }
      setError(messageFor(mutationError, "write"));
    } finally {
      setPendingMutation(null);
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Закрытый контур"
        title="Управление сбором"
        description="Просмотр последних запусков и узкое управление включением платформенных аккаунтов через защищённый Spring API."
        meta={authenticated ? <StatusPill tone="green">сессия активна</StatusPill> : <StatusPill tone="neutral">нужен вход</StatusPill>}
      />

      <aside className="my-4 rounded-lg border border-warning/30 bg-warning/10 p-4 text-warning [&>strong]:block [&>strong]:mb-1">
        <strong>Ограниченный административный срез.</strong> Здесь пока нет добавления и удаления вузов или аккаунтов,
        редактирования реквизитов, ручного запуска сбора, обновления M‑Рейтинга, диагностики интеграций и хранилища.
      </aside>

      {notice ? <p className="mb-4 rounded-lg border border-success/30 bg-success/10 p-4 text-success" role="status">{notice}</p> : null}
      {error ? <p className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-destructive" role="alert">{error}</p> : null}

      {!authenticated ? (
        <section className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm grid gap-7 lg:grid-cols-2" aria-busy={busy}>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">HTTP Basic + CSRF</p>
            <h2 className="font-heading text-lg font-semibold">Вход оператора</h2>
            <p className="mt-2 max-w-3xl text-xs leading-relaxed text-muted-foreground">Логин, пароль и CSRF-токен остаются только в памяти вкладки и удаляются при выходе или закрытии страницы.</p>
          </div>
          <form className="grid gap-3" onSubmit={authenticate} autoComplete="off">
            <label className="grid gap-1.5 text-sm"><span>Имя пользователя</span><Input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="off" maxLength={200} required /></label>
            <label className="grid gap-1.5 text-sm"><span>Пароль</span><Input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="off" maxLength={4096} required /></label>
            <NativeButton type="submit" disabled={busy}>{busy ? "Проверяем…" : "Войти"}</NativeButton>
          </form>
        </section>
      ) : (
        <>
          <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
            <p className="text-muted-foreground">Обновление страницы завершит сессию: учётные данные намеренно не сохраняются.</p>
            <NativeButton type="button" onClick={() => clearPrivateState("Административная сессия завершена.")}>Выйти</NativeButton>
          </div>

          <section className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm mt-0" aria-busy={busy}>
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Только чтение</p><h2 className="font-heading text-lg font-semibold">Запуски сбора</h2></div><StatusPill tone="neutral">до 100 строк</StatusPill></div>
            <form className="mb-5 grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-4" onSubmit={applyFilters}>
              <label className="grid gap-1.5 text-sm"><span>Площадка</span><NativeSelect value={platform} onChange={(event) => setPlatform(event.target.value as AdminPlatform)}>
                {ADMIN_PLATFORMS.map((value) => <option key={value || "all"} value={value}>{PLATFORM_LABELS[value]}</option>)}
              </NativeSelect></label>
              <label className="grid gap-1.5 text-sm"><span>Статус</span><NativeSelect value={status} onChange={(event) => setStatus(event.target.value as AdminJobStatus)}>
                {ADMIN_JOB_STATUSES.map((value) => <option key={value || "all"} value={value}>{STATUS_LABELS[value]}</option>)}
              </NativeSelect></label>
              <label className="grid gap-1.5 text-sm"><span>Лимит</span><Input type="number" min={1} max={100} value={limit} onChange={(event) => setLimit(Math.min(100, Math.max(1, Number(event.target.value) || 1)))} /></label>
              <NativeButton type="submit" disabled={busy}>{busy ? "Обновляем…" : "Обновить"}</NativeButton>
            </form>

            {jobs.length ? (
              <div className="min-w-0 overflow-x-auto">
                <Table>
                  <caption className="sr-only">Последние запуски сбора</caption>
                  <TableHeader><TableRow><TableHead>Старт</TableHead><TableHead>Площадка</TableHead><TableHead>Статус</TableHead><TableHead>Аккаунты</TableHead><TableHead>Ошибки</TableHead><TableHead>Действие</TableHead></TableRow></TableHeader>
                  <TableBody>{jobs.map((job) => (
                    <TableRow key={job.jobId}>
                      <TableCell>{dateTime(job.startedAt)}</TableCell><TableCell>{PLATFORM_LABELS[job.platform]}</TableCell>
                      <TableCell><StatusPill tone={statusTone(job.status)}>{STATUS_LABELS[job.status]}</StatusPill></TableCell>
                      <TableCell>{job.accountCount}</TableCell><TableCell>{job.errorCount}</TableCell>
                      <TableCell><NativeButton type="button" onClick={() => inspectJob(job.jobId)} aria-pressed={selectedJobId === job.jobId}>Подробнее</NativeButton></TableCell>
                    </TableRow>
                  ))}</TableBody>
                </Table>
              </div>
            ) : <div className="grid gap-2 rounded-lg border border-dashed p-5 text-muted-foreground" role="status"><strong>Запусков не найдено</strong><span>Измените фильтры или дождитесь следующего запуска сборщика.</span></div>}
          </section>

          {detailBusy ? <section className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm mt-5 grid gap-2 rounded-lg border border-dashed p-5 text-muted-foreground" role="status">Загружаем детали запуска…</section> : null}
          {!detailBusy && jobDetail ? (
            <section className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm mt-5">
              <div className="mb-5 flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Запуск {jobDetail.job.jobId}</p><h2 className="font-heading text-lg font-semibold">Результаты по аккаунтам</h2></div><StatusPill tone={statusTone(jobDetail.job.status)}>{STATUS_LABELS[jobDetail.job.status]}</StatusPill></div>
              <dl className="mb-5 grid gap-3 sm:grid-cols-3 [&>div]:min-w-0 [&>div]:rounded-lg [&>div]:border [&>div]:p-3 [&_dt]:text-xs [&_dt]:text-muted-foreground [&_dd]:mt-1 [&_dd]:break-all">
                <div><dt>Запланирован</dt><dd>{dateTime(jobDetail.job.scheduledAt)}</dd></div>
                <div><dt>Завершён</dt><dd>{dateTime(jobDetail.job.completedAt)}</dd></div>
                <div><dt>Correlation ID</dt><dd>{jobDetail.job.correlationId}</dd></div>
              </dl>
              {jobDetail.accountResults.length ? (
                <div className="min-w-0 overflow-x-auto">
                  <Table>
                    <caption className="sr-only">Результаты запуска по платформенным аккаунтам</caption>
                    <TableHeader><TableRow><TableHead>Аккаунт</TableHead><TableHead>Статус</TableHead><TableHead>Найдено</TableHead><TableHead>Снимки</TableHead><TableHead>Код ошибки</TableHead><TableHead>Действие</TableHead></TableRow></TableHeader>
                    <TableBody>{jobDetail.accountResults.map((result) => (
                      <TableRow key={result.resultId}>
                        <TableCell className="font-mono text-xs">{result.platformAccountId}</TableCell>
                        <TableCell><StatusPill tone={statusTone(result.status)}>{result.status}</StatusPill></TableCell>
                        <TableCell>{result.discoveredCount}</TableCell><TableCell>{result.snapshotCount}</TableCell><TableCell>{result.sanitizedErrorCode ?? "—"}</TableCell>
                        <TableCell><NativeButton type="button" onClick={() => void selectAccount(result.platformAccountId)}>Выбрать аккаунт</NativeButton></TableCell>
                      </TableRow>
                    ))}</TableBody>
                  </Table>
                </div>
              ) : <div className="grid gap-2 rounded-lg border border-dashed p-5 text-muted-foreground"><strong>Результатов по аккаунтам нет</strong><span>Запуск мог ещё не начать обработку аккаунтов.</span></div>}
              {jobDetail.accountResultsTruncated ? <p className="mt-2 max-w-3xl text-xs leading-relaxed text-muted-foreground">Показаны первые 100 результатов; ответ API помечен как усечённый.</p> : null}
            </section>
          ) : null}

          <section className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm mt-5 space-y-4">
            <div><p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Чтение: viewer · изменение: editor/admin</p><h2 className="font-heading text-lg font-semibold">Состояние платформенного аккаунта</h2><p className="mt-2 max-w-3xl text-xs leading-relaxed text-muted-foreground">Введите UUID или выберите аккаунт в результатах запуска. Перед подтверждением интерфейс получает актуальные enabled и rowVersion из защищённого API; вручную версия не принимается.</p></div>
            <form className="grid items-end gap-3 sm:grid-cols-[1fr_auto]" onSubmit={lookupAccount}>
              <label className="grid min-w-0 gap-1.5 text-sm"><span>UUID аккаунта</span><Input ref={mutationAccountRef} value={accountId} onChange={(event) => clearLoadedAccount(event.target.value)} placeholder="00000000-0000-4000-8000-000000000000" maxLength={36} spellCheck={false} autoComplete="off" required /></label>
              <NativeButton type="submit" disabled={accountBusy}>{accountBusy ? "Загружаем…" : "Загрузить состояние"}</NativeButton>
            </form>

            {accountState ? (
              <dl className="grid gap-3 rounded-lg border bg-muted/30 p-4 sm:grid-cols-2 lg:grid-cols-4 [&_dt]:text-xs [&_dt]:text-muted-foreground [&_dd]:mt-1 [&_dd]:break-all" aria-live="polite">
                <div><dt>Площадка</dt><dd>{PLATFORM_LABELS[accountState.platform]}</dd></div>
                <div><dt>Текущее состояние</dt><dd>{accountState.enabled ? "сбор включён" : "сбор отключён"}</dd></div>
                <div><dt>rowVersion</dt><dd>{accountState.rowVersion}</dd></div>
                <div><dt>Обновлено</dt><dd>{dateTime(accountState.updatedAt)}</dd></div>
              </dl>
            ) : null}

            <form className="grid gap-3 sm:grid-cols-2" onSubmit={prepareMutation}>
              <label className="grid gap-1.5 text-sm"><span>Новое состояние</span><NativeSelect value={desiredEnabled ? "enabled" : "disabled"} onChange={(event) => setDesiredEnabled(event.target.value === "enabled")}><option value="enabled">Сбор включён</option><option value="disabled">Сбор отключён</option></NativeSelect></label>
              <NativeButton type="submit" disabled={busy || accountBusy || !accountState}>Проверить изменение</NativeButton>
            </form>

            {pendingMutation ? (
              <div className="rounded-lg border border-warning/30 bg-warning/10 p-4 space-y-3" role="alert" aria-labelledby="mutation-confirm-title" aria-describedby="mutation-confirm-description">
                <h3 id="mutation-confirm-title">Подтвердите изменение</h3>
                <p id="mutation-confirm-description">Аккаунт <code>{pendingMutation.accountId}</code>: {pendingMutation.enabled ? "включить" : "отключить"} сбор при rowVersion {pendingMutation.expectedRowVersion}. Операция попадёт в аудит.</p>
                <div className="flex flex-wrap gap-2"><NativeButton type="button" onClick={confirmMutation} disabled={busy}>{busy ? "Изменяем…" : "Подтвердить"}</NativeButton><NativeButton type="button" onClick={() => setPendingMutation(null)} disabled={busy}>Отмена</NativeButton></div>
              </div>
            ) : null}

            {mutationResult ? (
              <dl className="mt-4 grid gap-3 sm:grid-cols-3 [&>div]:rounded-lg [&>div]:border [&>div]:p-3 [&_dt]:text-muted-foreground [&_dd]:break-all" aria-live="polite">
                <div><dt>Состояние</dt><dd>{mutationResult.account.enabled ? "включён" : "отключён"}</dd></div>
                <div><dt>rowVersion</dt><dd>{mutationResult.account.rowVersion}</dd></div>
                <div><dt>Ревизия данных</dt><dd>{mutationResult.datasetRevision ?? "без изменения"}</dd></div>
                <div><dt>Обновлено</dt><dd>{dateTime(mutationResult.account.updatedAt)}</dd></div>
              </dl>
            ) : null}
          </section>
        </>
      )}
    </>
  );
}
