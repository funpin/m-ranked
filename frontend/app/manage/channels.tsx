import { randomUUID } from "node:crypto";
import { RefreshCw } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CatalogDialogs } from "@/components/catalog-forms";
import type { CatalogStatus, ManagedInstitution } from "@/lib/catalog-api";
import { legacyDate, PLATFORM_LONG_LABELS } from "@/lib/format";
import { AccountsTable } from "./accounts-table";
import { fields, Pill, plural, Section } from "./shared";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function RatingSection({ status, outcome, csrf, canEdit }: {
  status: CatalogStatus | null; outcome: string | undefined; csrf: string; canEdit: boolean;
}) {
  const period = status ? status.mRating.period || "ещё не загружен" : "статус не получен";
  return (
    <Section title="Официальный М‑Рейтинг · соцсети"
      description={<>Для каждого вуза загружаются общий рейтинг соцсетей и отдельные места в Telegram, VK, MAX и Rutube. Последний период: <b>{period}</b>{status?.mRating.updatedAt ? ` · обновлено ${legacyDate(status.mRating.updatedAt, true)}` : ""}.</>}
      action={<form method="post" action="/manage/m-rating/update">{fields(csrf)}
        <Button type="submit" variant="outline" disabled={!canEdit}><RefreshCw data-icon="inline-start" aria-hidden="true" />Загрузить свежий М‑Рейтинг</Button>
      </form>}>
      {outcome === "updated" ? <p className="text-success">Пять срезов М‑Рейтинга обновлены.</p>
        : outcome === "error" ? <p className="text-destructive">Не удалось обновить М‑Рейтинг: {status?.mRating.error || "неизвестная ошибка"}</p>
          : status?.mRating.error ? <p className="text-destructive">Последняя попытка: {status.mRating.error}</p> : null}
    </Section>
  );
}

function IntegrationsSection({ status }: { status: CatalogStatus | null }) {
  return (
    <Section title="Подключения API" description="Значения секретов хранятся только в окружении сервера и никогда не выводятся в браузер.">
      {status
        ? <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {status.integrations.map((integration) => (
            <article key={integration.platform} className="min-w-0 rounded-lg border p-4">
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2 text-xs">
                <b>{PLATFORM_LONG_LABELS[integration.platform]}</b>
                <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${integration.status === "configured" ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`}>
                  {integration.status === "configured" ? "подключено" : integration.status === "missing" ? "нужна настройка" : "статус не получен"}
                </span>
              </div>
              <small className="text-muted-foreground text-xs leading-relaxed">{integration.detail}</small>
            </article>
          ))}
        </div>
        : <p className="text-destructive" role="status">Не удалось получить состояние подключений.</p>}
    </Section>
  );
}

export function ChannelsTab({ institutions, status, selectedId, csrf, canEdit, canDelete, message, commandError, correlation, ratingOutcome }: {
  institutions: ManagedInstitution[]; status: CatalogStatus | null; selectedId: number | null; csrf: string;
  canEdit: boolean; canDelete: boolean; message?: string; commandError?: string; correlation: string; ratingOutcome?: string;
}) {
  const platformCount = status?.platformCount ?? institutions.reduce((sum, row) => sum + row.accounts.length, 0);
  return <>
    <RatingSection status={status} outcome={ratingOutcome} csrf={csrf} canEdit={canEdit} />
    <IntegrationsSection status={status} />
    <Section title="Вузы и аккаунты в соцсетях"
      description="VK сохраняет просмотры, лайки, комментарии и репосты. MAX читает публичные каналы через отдельную пользовательскую сессию и сохраняет просмотры и реакции. Rutube получает просмотры, лайки и комментарии из официальных публичных API без токена."
      action={<Pill>{platformCount} {plural(platformCount, "аккаунт", "аккаунта", "аккаунтов")} · {institutions.length} {plural(institutions.length, "вуз", "вуза", "вузов")}</Pill>}>
      {message ? <Alert role="status" className="border-success/30 bg-success/10 text-success my-4 p-4 text-sm">{message}</Alert> : null}
      {commandError ? <Alert variant="destructive" className="border-destructive/30 bg-destructive/10 my-4 block p-4 text-sm">{commandError}{UUID.test(correlation) ? <> Код операции: <code>{correlation}</code>.</> : null}</Alert> : null}
      {!canEdit ? <p className="my-4 rounded-lg border p-4 text-sm">Доступен просмотр. Изменения выполняют редакторы и администраторы.</p> : null}
      <CatalogDialogs institutions={institutions} selectedId={selectedId} csrfToken={csrf} correlationIds={[randomUUID(), randomUUID()]} canEdit={canEdit} />
      <AccountsTable institutions={institutions} status={status} csrf={csrf} canEdit={canEdit} canDelete={canDelete} />
    </Section>
  </>;
}
