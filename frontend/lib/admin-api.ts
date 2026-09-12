import type { ApiProblem } from "./types";

type Fetcher = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export const ADMIN_PLATFORMS = ["", "telegram", "vk", "max", "rutube"] as const;
export const ADMIN_JOB_STATUSES = [
  "",
  "pending",
  "running",
  "succeeded",
  "partial",
  "failed",
  "skipped",
  "cancelled",
] as const;

export type AdminPlatform = (typeof ADMIN_PLATFORMS)[number];
export type AdminJobStatus = (typeof ADMIN_JOB_STATUSES)[number];

export interface AdminJob {
  jobId: string;
  kind: "collection";
  platform: Exclude<AdminPlatform, "">;
  scheduledAt: string;
  startedAt: string;
  completedAt: string | null;
  status: Exclude<AdminJobStatus, "">;
  accountCount: number;
  errorCount: number;
  correlationId: string;
}

export interface AdminJobPage {
  items: AdminJob[];
}

export interface AdminAccountResult {
  resultId: number;
  platformAccountId: string;
  startedAt: string;
  completedAt: string | null;
  status: string;
  discoveredCount: number;
  snapshotCount: number;
  sanitizedErrorCode: string | null;
}

export interface AdminJobDetail {
  job: AdminJob;
  accountResults: AdminAccountResult[];
  accountResultsTruncated: boolean;
}

export interface PlatformAccountAdminState {
  accountId: string;
  platform: Exclude<AdminPlatform, "">;
  enabled: boolean;
  rowVersion: number;
  updatedAt: string;
}

export interface SetEnabledResponse {
  account: PlatformAccountAdminState;
  changed: boolean;
  datasetRevision: number | null;
  correlationId: string;
  outcome: "updated" | "idempotent";
}

export interface AdminCredentials {
  username: string;
  password: string;
}

export interface JobsQuery {
  platform?: AdminPlatform;
  status?: AdminJobStatus;
  limit?: number;
}

export interface AdminSession {
  initialize(): Promise<void>;
  jobs(query?: JobsQuery): Promise<AdminJobPage>;
  job(jobId: string, accountResultLimit?: number): Promise<AdminJobDetail>;
  account(accountId: string): Promise<PlatformAccountAdminState>;
  setAccountEnabled(input: {
    accountId: string;
    enabled: boolean;
    expectedRowVersion: number;
  }): Promise<SetEnabledResponse>;
  close(): void;
}

export interface AdminSessionOptions {
  fetcher?: Fetcher;
  origin?: string;
  timeoutMs?: number;
  randomUuid?: () => string;
}

interface CsrfResponse {
  headerName: string;
  parameterName: string;
  token: string;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const EXPECTED_CSRF_HEADER = "x-xsrf-token";
const CONCRETE_ADMIN_PLATFORMS = new Set<Exclude<AdminPlatform, "">>([
  "telegram",
  "vk",
  "max",
  "rutube",
]);

export class AdminApiError extends Error {
  readonly status: number;
  readonly problem: ApiProblem | null;

  constructor(status: number, message: string, problem: ApiProblem | null = null) {
    super(message);
    this.name = "AdminApiError";
    this.status = status;
    this.problem = problem;
  }
}

function requireCredentials(input: AdminCredentials): { username: string; password: string } {
  const username = input.username.trim();
  if (
    !username
    || username.length > 200
    || username.includes(":")
    || Array.from(username).some((value) => /\p{Cc}/u.test(value))
  ) {
    throw new AdminApiError(0, "Введите корректное имя пользователя");
  }
  if (!input.password || input.password.length > 4_096) {
    throw new AdminApiError(0, "Введите корректный пароль");
  }
  return { username, password: input.password };
}

function base64Utf8(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function resolvedOrigin(explicit?: string): string {
  const source = explicit ?? (typeof window === "undefined" ? "" : window.location.origin);
  if (!source) throw new AdminApiError(0, "Административный API требует браузерный same-origin контекст");
  const parsed = new URL(source);
  if (
    (parsed.protocol !== "https:" && parsed.protocol !== "http:")
    || parsed.username
    || parsed.password
    || parsed.pathname !== "/"
    || parsed.search
    || parsed.hash
  ) {
    throw new AdminApiError(0, "Некорректный origin административного API");
  }
  return parsed.origin;
}

function boundedInteger(value: number | undefined, fallback: number, minimum: number, maximum: number): number {
  if (value === undefined || !Number.isFinite(value)) return fallback;
  return Math.min(maximum, Math.max(minimum, Math.trunc(value)));
}

function requireUuid(value: string, label: string): string {
  const normalized = value.trim().toLowerCase();
  if (!UUID_PATTERN.test(normalized)) throw new AdminApiError(0, `${label} должен быть UUID`);
  return normalized;
}

function requireRowVersion(value: number): number {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new AdminApiError(0, "rowVersion должен быть неотрицательным безопасным целым числом");
  }
  return value;
}

function requireAccountState(value: unknown, expectedAccountId: string): PlatformAccountAdminState {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new AdminApiError(502, "Административный API вернул некорректное состояние аккаунта");
  }
  const supplied = value as Partial<PlatformAccountAdminState>;
  let accountId: string;
  try {
    accountId = requireUuid(String(supplied.accountId ?? ""), "Идентификатор аккаунта в ответе");
    requireRowVersion(supplied.rowVersion as number);
  } catch {
    throw new AdminApiError(502, "Административный API вернул некорректное состояние аккаунта");
  }
  if (
    accountId !== expectedAccountId
    || !CONCRETE_ADMIN_PLATFORMS.has(supplied.platform as Exclude<AdminPlatform, "">)
    || typeof supplied.enabled !== "boolean"
    || typeof supplied.updatedAt !== "string"
    || Number.isNaN(Date.parse(supplied.updatedAt))
  ) {
    throw new AdminApiError(502, "Административный API вернул некорректное состояние аккаунта");
  }
  return {
    accountId,
    platform: supplied.platform as Exclude<AdminPlatform, "">,
    enabled: supplied.enabled,
    rowVersion: supplied.rowVersion as number,
    updatedAt: supplied.updatedAt,
  };
}

async function problemFrom(response: Response): Promise<ApiProblem | null> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("json")) return null;
  try {
    return (await response.json()) as ApiProblem;
  } catch {
    return null;
  }
}

function problemMessage(status: number, problem: ApiProblem | null): string {
  const supplied = problem?.detail || problem?.title;
  if (supplied) return supplied.slice(0, 500);
  if (status === 401) return "Authentication is required";
  if (status === 403) return "Access to this resource is denied";
  if (status === 409) return "The platform account changed after it was read";
  return `Admin API request failed with ${status}`;
}

function parseJson<T>(response: Response): Promise<T> {
  return response.json().catch(() => {
    throw new AdminApiError(502, "Административный API вернул некорректный JSON");
  }) as Promise<T>;
}

export function createAdminSession(
  suppliedCredentials: AdminCredentials,
  options: AdminSessionOptions = {},
): AdminSession {
  const credentials = requireCredentials(suppliedCredentials);
  const origin = resolvedOrigin(options.origin);
  const fetcher: Fetcher = options.fetcher ?? ((input, init) => fetch(input, init));
  const timeoutMs = boundedInteger(options.timeoutMs, 8_000, 1_000, 30_000);
  const randomUuid = options.randomUuid ?? (() => crypto.randomUUID());
  let authorization = `Basic ${base64Utf8(`${credentials.username}:${credentials.password}`)}`;
  let csrfToken = "";
  let closed = false;

  async function request<T>(
    path: string,
    init: { method?: "GET" | "PUT"; body?: string; csrf?: boolean; correlationId?: string } = {},
  ): Promise<T> {
    if (closed || !authorization) throw new AdminApiError(401, "Административная сессия завершена");
    const url = new URL(path, origin);
    if (url.origin !== origin || !url.pathname.startsWith("/api/v1/admin/")) {
      throw new AdminApiError(0, "Запрос вышел за границы административного API");
    }
    const headers = new Headers({
      Accept: "application/json, application/problem+json",
      Authorization: authorization,
    });
    if (init.body !== undefined) headers.set("Content-Type", "application/json");
    if (init.csrf) {
      if (!csrfToken) throw new AdminApiError(403, "CSRF-сессия не инициализирована");
      headers.set("X-XSRF-TOKEN", csrfToken);
    }
    if (init.correlationId) headers.set("X-Correlation-Id", init.correlationId);

    let response: Response;
    try {
      response = await fetcher(url, {
        method: init.method ?? "GET",
        headers,
        body: init.body,
        cache: "no-store",
        credentials: "same-origin",
        redirect: "error",
        referrerPolicy: "no-referrer",
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch {
      throw new AdminApiError(0, "Административный API недоступен");
    }
    if (!response.ok) {
      const problem = await problemFrom(response);
      throw new AdminApiError(response.status, problemMessage(response.status, problem), problem);
    }
    return parseJson<T>(response);
  }

  const session: AdminSession = {
    async initialize(): Promise<void> {
      const response = await request<CsrfResponse>("/api/v1/admin/csrf");
      if (
        typeof response?.headerName !== "string"
        || response.headerName.toLowerCase() !== EXPECTED_CSRF_HEADER
        || typeof response.token !== "string"
        || !response.token
        || response.token.length > 4_096
      ) {
        throw new AdminApiError(502, "Административный API вернул некорректный CSRF-контракт");
      }
      csrfToken = response.token;
    },

    async jobs(query: JobsQuery = {}): Promise<AdminJobPage> {
      const platform = query.platform ?? "";
      const status = query.status ?? "";
      if (!ADMIN_PLATFORMS.includes(platform)) throw new AdminApiError(0, "Недопустимый фильтр платформы");
      if (!ADMIN_JOB_STATUSES.includes(status)) throw new AdminApiError(0, "Недопустимый фильтр статуса");
      const url = new URL("/api/v1/admin/jobs", origin);
      if (platform) url.searchParams.set("platform", platform);
      if (status) url.searchParams.set("status", status);
      url.searchParams.set("limit", String(boundedInteger(query.limit, 50, 1, 100)));
      return request<AdminJobPage>(url.pathname + url.search);
    },

    async job(jobId: string, accountResultLimit = 100): Promise<AdminJobDetail> {
      const id = requireUuid(jobId, "Идентификатор запуска");
      const limit = boundedInteger(accountResultLimit, 100, 1, 200);
      return request<AdminJobDetail>(`/api/v1/admin/jobs/${id}?accountResultLimit=${limit}`);
    },

    async account(accountId: string): Promise<PlatformAccountAdminState> {
      const id = requireUuid(accountId, "Идентификатор аккаунта");
      const response = await request<unknown>(`/api/v1/admin/platform-accounts/${id}`);
      return requireAccountState(response, id);
    },

    async setAccountEnabled(input): Promise<SetEnabledResponse> {
      const accountId = requireUuid(input.accountId, "Идентификатор аккаунта");
      const expectedRowVersion = requireRowVersion(input.expectedRowVersion);
      const correlationId = requireUuid(randomUuid(), "Correlation ID");
      const response = await request<SetEnabledResponse>(
        `/api/v1/admin/platform-accounts/${accountId}/enabled`,
        {
          method: "PUT",
          csrf: true,
          correlationId,
          body: JSON.stringify({ enabled: input.enabled, expectedRowVersion }),
        },
      );
      return { ...response, account: requireAccountState(response.account, accountId) };
    },

    close(): void {
      authorization = "";
      csrfToken = "";
      closed = true;
    },
  };
  return Object.freeze(session);
}

export async function withConflictRefresh<T>(
  operation: () => Promise<T>,
  refresh: () => Promise<void>,
): Promise<T> {
  try {
    return await operation();
  } catch (error) {
    if (error instanceof AdminApiError && error.status === 409) {
      try {
        await refresh();
      } catch {
        // Preserve the actionable optimistic-lock response even if the refresh also fails.
      }
    }
    throw error;
  }
}
