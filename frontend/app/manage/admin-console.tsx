"use client";

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
import styles from "./manage.module.css";

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

      <aside className={`notice notice-amber ${styles.scopeNotice}`}>
        <strong>Ограниченный административный срез.</strong> Здесь пока нет добавления и удаления вузов или аккаунтов,
        редактирования реквизитов, ручного запуска сбора, обновления M‑Рейтинга, диагностики интеграций и хранилища.
      </aside>

      {notice ? <p className={styles.success} role="status">{notice}</p> : null}
      {error ? <p className={styles.error} role="alert">{error}</p> : null}

      {!authenticated ? (
        <section className={`panel ${styles.loginPanel}`} aria-busy={busy}>
          <div>
            <p className="eyebrow">HTTP Basic + CSRF</p>
            <h2>Вход оператора</h2>
            <p className={styles.help}>Логин, пароль и CSRF-токен остаются только в памяти вкладки и удаляются при выходе или закрытии страницы.</p>
          </div>
          <form className={styles.loginForm} onSubmit={authenticate} autoComplete="off">
            <label className="field"><span>Имя пользователя</span><input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="off" maxLength={200} required /></label>
            <label className="field"><span>Пароль</span><input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="off" maxLength={4096} required /></label>
            <button type="submit" disabled={busy}>{busy ? "Проверяем…" : "Войти"}</button>
          </form>
        </section>
      ) : (
        <>
          <div className={styles.sessionActions}>
            <p className="muted">Обновление страницы завершит сессию: учётные данные намеренно не сохраняются.</p>
            <button type="button" className="secondary-button" onClick={() => clearPrivateState("Административная сессия завершена.")}>Выйти</button>
          </div>

          <section className={`panel ${styles.jobsPanel}`} aria-busy={busy}>
            <div className="section-head"><div><p className="eyebrow">Только чтение</p><h2>Запуски сбора</h2></div><StatusPill tone="neutral">до 100 строк</StatusPill></div>
            <form className={styles.filters} onSubmit={applyFilters}>
              <label className="field"><span>Площадка</span><select value={platform} onChange={(event) => setPlatform(event.target.value as AdminPlatform)}>
                {ADMIN_PLATFORMS.map((value) => <option key={value || "all"} value={value}>{PLATFORM_LABELS[value]}</option>)}
              </select></label>
              <label className="field"><span>Статус</span><select value={status} onChange={(event) => setStatus(event.target.value as AdminJobStatus)}>
                {ADMIN_JOB_STATUSES.map((value) => <option key={value || "all"} value={value}>{STATUS_LABELS[value]}</option>)}
              </select></label>
              <label className="field"><span>Лимит</span><input type="number" min={1} max={100} value={limit} onChange={(event) => setLimit(Math.min(100, Math.max(1, Number(event.target.value) || 1)))} /></label>
              <button type="submit" disabled={busy}>{busy ? "Обновляем…" : "Обновить"}</button>
            </form>

            {jobs.length ? (
              <div className="table-wrap">
                <table>
                  <caption className="sr-only">Последние запуски сбора</caption>
                  <thead><tr><th>Старт</th><th>Площадка</th><th>Статус</th><th>Аккаунты</th><th>Ошибки</th><th>Действие</th></tr></thead>
                  <tbody>{jobs.map((job) => (
                    <tr key={job.jobId}>
                      <td>{dateTime(job.startedAt)}</td><td>{PLATFORM_LABELS[job.platform]}</td>
                      <td><StatusPill tone={statusTone(job.status)}>{STATUS_LABELS[job.status]}</StatusPill></td>
                      <td>{job.accountCount}</td><td>{job.errorCount}</td>
                      <td><button type="button" className="secondary-button" onClick={() => inspectJob(job.jobId)} aria-pressed={selectedJobId === job.jobId}>Подробнее</button></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            ) : <div className={styles.empty} role="status"><strong>Запусков не найдено</strong><span>Измените фильтры или дождитесь следующего запуска сборщика.</span></div>}
          </section>

          {detailBusy ? <section className={`panel section ${styles.empty}`} role="status">Загружаем детали запуска…</section> : null}
          {!detailBusy && jobDetail ? (
            <section className="panel section">
              <div className="section-head"><div><p className="eyebrow">Запуск {jobDetail.job.jobId}</p><h2>Результаты по аккаунтам</h2></div><StatusPill tone={statusTone(jobDetail.job.status)}>{STATUS_LABELS[jobDetail.job.status]}</StatusPill></div>
              <dl className={styles.jobFacts}>
                <div><dt>Запланирован</dt><dd>{dateTime(jobDetail.job.scheduledAt)}</dd></div>
                <div><dt>Завершён</dt><dd>{dateTime(jobDetail.job.completedAt)}</dd></div>
                <div><dt>Correlation ID</dt><dd>{jobDetail.job.correlationId}</dd></div>
              </dl>
              {jobDetail.accountResults.length ? (
                <div className="table-wrap">
                  <table>
                    <caption className="sr-only">Результаты запуска по платформенным аккаунтам</caption>
                    <thead><tr><th>Аккаунт</th><th>Статус</th><th>Найдено</th><th>Снимки</th><th>Код ошибки</th><th>Действие</th></tr></thead>
                    <tbody>{jobDetail.accountResults.map((result) => (
                      <tr key={result.resultId}>
                        <td className={styles.uuidCell}>{result.platformAccountId}</td>
                        <td><StatusPill tone={statusTone(result.status)}>{result.status}</StatusPill></td>
                        <td>{result.discoveredCount}</td><td>{result.snapshotCount}</td><td>{result.sanitizedErrorCode ?? "—"}</td>
                        <td><button type="button" className="secondary-button" onClick={() => void selectAccount(result.platformAccountId)}>Выбрать аккаунт</button></td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              ) : <div className={styles.empty}><strong>Результатов по аккаунтам нет</strong><span>Запуск мог ещё не начать обработку аккаунтов.</span></div>}
              {jobDetail.accountResultsTruncated ? <p className={styles.help}>Показаны первые 100 результатов; ответ API помечен как усечённый.</p> : null}
            </section>
          ) : null}

          <section className={`panel section ${styles.mutationPanel}`}>
            <div><p className="eyebrow">Чтение: viewer · изменение: editor/admin</p><h2>Состояние платформенного аккаунта</h2><p className={styles.help}>Введите UUID или выберите аккаунт в результатах запуска. Перед подтверждением интерфейс получает актуальные enabled и rowVersion из защищённого API; вручную версия не принимается.</p></div>
            <form className={styles.lookupForm} onSubmit={lookupAccount}>
              <label className={`field ${styles.accountField}`}><span>UUID аккаунта</span><input ref={mutationAccountRef} value={accountId} onChange={(event) => clearLoadedAccount(event.target.value)} placeholder="00000000-0000-4000-8000-000000000000" maxLength={36} spellCheck={false} autoComplete="off" required /></label>
              <button type="submit" className="secondary-button" disabled={accountBusy}>{accountBusy ? "Загружаем…" : "Загрузить состояние"}</button>
            </form>

            {accountState ? (
              <dl className={styles.accountState} aria-live="polite">
                <div><dt>Площадка</dt><dd>{PLATFORM_LABELS[accountState.platform]}</dd></div>
                <div><dt>Текущее состояние</dt><dd>{accountState.enabled ? "сбор включён" : "сбор отключён"}</dd></div>
                <div><dt>rowVersion</dt><dd>{accountState.rowVersion}</dd></div>
                <div><dt>Обновлено</dt><dd>{dateTime(accountState.updatedAt)}</dd></div>
              </dl>
            ) : null}

            <form className={styles.commandForm} onSubmit={prepareMutation}>
              <label className="field"><span>Новое состояние</span><select value={desiredEnabled ? "enabled" : "disabled"} onChange={(event) => setDesiredEnabled(event.target.value === "enabled")}><option value="enabled">Сбор включён</option><option value="disabled">Сбор отключён</option></select></label>
              <button type="submit" disabled={busy || accountBusy || !accountState}>Проверить изменение</button>
            </form>

            {pendingMutation ? (
              <div className={styles.confirmation} role="alert" aria-labelledby="mutation-confirm-title" aria-describedby="mutation-confirm-description">
                <h3 id="mutation-confirm-title">Подтвердите изменение</h3>
                <p id="mutation-confirm-description">Аккаунт <code>{pendingMutation.accountId}</code>: {pendingMutation.enabled ? "включить" : "отключить"} сбор при rowVersion {pendingMutation.expectedRowVersion}. Операция попадёт в аудит.</p>
                <div className={styles.confirmationActions}><button type="button" onClick={confirmMutation} disabled={busy}>{busy ? "Изменяем…" : "Подтвердить"}</button><button type="button" className="secondary-button" onClick={() => setPendingMutation(null)} disabled={busy}>Отмена</button></div>
              </div>
            ) : null}

            {mutationResult ? (
              <dl className={styles.result} aria-live="polite">
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
