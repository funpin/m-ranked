import type { ReactNode } from "react";
import { CircleCheck, CirclePause, Pause, Pencil, Play, Trash2, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TableCell } from "@/components/ui/table";
import { PlatformChip } from "@/components/platform-chip";
import { DeleteCatalogForm } from "@/components/catalog-forms";
import type { CatalogStatus, ManagedAccount, ManagedInstitution, OfficialRating } from "@/lib/catalog-api";
import { cn } from "@/lib/utils";
import { CatalogDataTable, type AccountState, type CatalogGroup } from "./catalog-table";
import { fields } from "./shared";

const ACCESS_MODES: Record<string, string> = {
  public: "публичный доступ", user_session: "пользовательская сессия", owner: "нужен доступ владельца",
};

function ratingScore(value: number | null) {
  if (value === null) return "—";
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? rounded.toFixed(1) : String(rounded);
}

function Rating({ rating, label }: { rating: OfficialRating | undefined; label: string }) {
  if (rating === undefined) return <>{label}: статус не получен</>;
  return rating.rank ? <><b>{label} №{rating.rank}</b> · {ratingScore(rating.score)}</> : <>{label} —</>;
}

/** Кнопка-значок с подсказкой на CSS: в таблице сотни строк, и клиентская
 *  подсказка на каждую кнопку стоила бы заметной гидратации. */
function IconAction({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="group/tip relative inline-flex">
      {children}
      <span aria-hidden="true"
        className="bg-foreground text-background pointer-events-none absolute top-1/2 right-full z-10 mr-1.5 translate-x-1 -translate-y-1/2 rounded-md px-2 py-1 text-xs whitespace-nowrap opacity-0 shadow-md transition-[opacity,translate] duration-150 group-hover/tip:translate-x-0 group-hover/tip:opacity-100 group-focus-within/tip:translate-x-0 group-focus-within/tip:opacity-100">
        {label}
      </span>
    </span>
  );
}

function InstitutionInfo({ institution, csrf, canEdit, withRating = true }: {
  institution: ManagedInstitution; csrf: string; canEdit: boolean; withRating?: boolean;
}) {
  return <>
    <b title={institution.name}>{institution.shortName || institution.name}</b>
    <small>{institution.name}</small>
    {withRating ? <small><Rating rating={institution.officialRatings?.all} label="Общий М‑Рейтинг" /></small> : null}
    <details className="group/rename mt-2 [&_form]:mt-3 [&_form]:grid [&_form]:gap-3">
      <summary aria-label="Редактировать название"
        className="text-muted-foreground hover:text-foreground inline-flex cursor-pointer list-none items-center gap-1.5 text-xs [&::-webkit-details-marker]:hidden">
        <Pencil className="size-3" aria-hidden="true" />Переименовать
      </summary>
      <form method="post" action={`/manage/institutions/${institution.legacyId}`}>
        <Label className="grid gap-1.5 text-sm leading-normal font-normal">Полное название
          <Input name="name" defaultValue={institution.name} required disabled={!canEdit} /></Label>
        <Label className="grid gap-1.5 text-sm leading-normal font-normal">Сокращение
          <Input name="short_name" defaultValue={institution.shortName || institution.name} required disabled={!canEdit} /></Label>
        {fields(csrf, institution.rowVersion)}
        <Button type="submit" disabled={!canEdit}>Сохранить</Button>
      </form>
    </details>
  </>;
}

function statusText(account: ManagedAccount, status: CatalogStatus | null) {
  const integration = status?.integrations.find((row) => row.platform === account.platform)?.status;
  if (!account.enabled) return "отключён";
  if (integration === "unknown" || integration === undefined) return "статус не получен";
  if (account.platform === "telegram") return "работает";
  if (account.platform === "vk") return integration === "configured" ? "работает" : "нужен токен";
  if (account.platform === "max") return integration !== "configured" ? "нужна сессия" : !account.nativeId ? "ожидает подписки" : "работает";
  return integration === "configured" ? "работает" : "сбор выключен";
}

function accountState(text: string): AccountState {
  return text === "работает" ? "ok" : text === "отключён" ? "off" : "attention";
}

/** Статус как в data-table shadcn: контурный бейдж со значком, не только цветом. */
function AccountStatus({ account, status }: { account: ManagedAccount; status: CatalogStatus | null }) {
  const text = statusText(account, status);
  const state = accountState(text);
  const Icon = state === "ok" ? CircleCheck : state === "off" ? CirclePause : TriangleAlert;
  return <Badge variant="outline" className="text-muted-foreground h-6 gap-1 px-2 text-xs font-medium">
    <Icon aria-hidden="true" className={cn("size-3.5!", state === "ok" ? "fill-success text-card" : state === "attention" ? "text-warning" : "")} />{text}
  </Badge>;
}

function PlatformLabel({ account }: { account: ManagedAccount }) {
  return <PlatformChip platform={account.platform} label={account.platform.toUpperCase()} />;
}

function AccountName({ account }: { account: ManagedAccount }) {
  const name = account.title || (account.username ? `@${account.username}` : account.externalKey);
  return <>
    {account.url && /^https?:\/\//.test(account.url)
      ? <a href={account.url} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4">{name} ↗</a>
      : name}
    {account.platform === "max" && account.nativeId ? <small>chat_id {account.nativeId}</small> : null}
  </>;
}

function Actions({ account, csrf, canEdit, canDelete }: {
  account: ManagedAccount; csrf: string; canEdit: boolean; canDelete: boolean;
}) {
  const toggle = account.enabled ? "Отключить" : "Включить";
  return (
    <div className="flex items-center justify-end gap-1">
      <form method="post" action={`/manage/platform-accounts/${account.legacyId}/${account.enabled ? "disable" : "enable"}`}>
        {fields(csrf, account.rowVersion)}
        <IconAction label={account.enabled ? "Остановить сбор" : "Возобновить сбор"}>
          <Button type="submit" variant="outline" size="icon-sm" aria-label={toggle} disabled={!canEdit}>
            {account.enabled ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
          </Button>
        </IconAction>
      </form>
      <DeleteCatalogForm method="post" action={`/manage/platform-accounts/${account.legacyId}/delete`}>
        {fields(csrf, account.rowVersion)}
        <IconAction label="Удалить аккаунт и данные">
          <Button type="submit" variant="destructive" size="icon-sm" aria-label="Удалить" disabled={!canDelete}>
            <Trash2 aria-hidden="true" />
          </Button>
        </IconAction>
      </DeleteCatalogForm>
    </div>
  );
}

/** Вузы и аккаунты: ячейки и формы рисует сервер, поиск, фильтры, страницы
 *  и массовые действия — клиентская таблица CatalogDataTable. */
export function AccountsTable({ institutions, status, csrf, canEdit, canDelete }: {
  institutions: ManagedInstitution[]; status: CatalogStatus | null; csrf: string; canEdit: boolean; canDelete: boolean;
}) {
  const lower = (...values: (string | null | undefined)[]) => values.filter(Boolean).join(" ").toLowerCase();
  const groups: CatalogGroup[] = institutions.map((institution) => ({
    id: institution.id,
    search: lower(institution.name, institution.shortName),
    header: <InstitutionInfo institution={institution} csrf={csrf} canEdit={canEdit} withRating={institution.accounts.length > 0} />,
    accounts: institution.accounts.map((account) => ({
      id: account.id, legacyId: account.legacyId, rowVersion: account.rowVersion, enabled: account.enabled, platform: account.platform,
      state: accountState(statusText(account, status)),
      search: lower(account.title, account.username, account.externalKey, account.nativeId, account.url),
      cells: <>
        <TableCell><PlatformLabel account={account} /></TableCell>
        <TableCell className="min-w-48"><AccountName account={account} /></TableCell>
        <TableCell className="min-w-40">
          <small className="!mt-0">
            {account.channelId !== null
              ? <>{account.subscribers || "—"} подписчиков<br /></>
              : <>{ACCESS_MODES[account.legacyAccessMode ?? account.accessMode] || account.legacyAccessMode || account.accessMode}<br /></>}
            <Rating rating={institution.officialRatings?.[account.platform]} label={`М‑Рейтинг ${account.platform.toUpperCase()}`} />
          </small>
        </TableCell>
        <TableCell>
          <AccountStatus account={account} status={status} />
          {account.lastErrorCode
            ? <small className="text-destructive">{account.lastErrorCode === "legacy_collection_error" ? "Ошибка предыдущего сбора" : "Ошибка сбора данных"}</small>
            : null}
        </TableCell>
        <TableCell><Actions account={account} csrf={csrf} canEdit={canEdit} canDelete={canDelete} /></TableCell>
      </>,
    })),
  }));
  return <CatalogDataTable groups={groups} csrf={csrf} canEdit={canEdit} canDelete={canDelete} />;
}
