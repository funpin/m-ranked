import type { ReactNode } from "react";
import { Pause, Pencil, Play, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PlatformChip } from "@/components/platform-chip";
import { DeleteCatalogForm } from "@/components/catalog-forms";
import type { CatalogStatus, ManagedAccount, ManagedInstitution, OfficialRating } from "@/lib/catalog-api";
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

function InstitutionCell({ institution, csrf, canEdit, withRating = true }: {
  institution: ManagedInstitution; csrf: string; canEdit: boolean; withRating?: boolean;
}) {
  // Непрозрачный фон: ячейка вуза охватывает несколько строк, и подсветка
  // строки иначе красила бы её только при наведении на первую из них.
  return (
    <TableCell rowSpan={Math.max(1, institution.accounts.length)} className="bg-card min-w-56 space-y-1 align-top">
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
    </TableCell>
  );
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

function AccountStatus({ account, status }: { account: ManagedAccount; status: CatalogStatus | null }) {
  const text = statusText(account, status);
  const tone = text === "работает" ? "bg-success/10 text-success" : text === "отключён" ? "bg-muted text-muted-foreground" : "bg-warning/10 text-warning";
  return <Badge className={`h-auto text-xs ${tone}`}>{text}</Badge>;
}

function PlatformLabel({ account, csrf, canEdit }: { account: ManagedAccount; csrf: string; canEdit: boolean }) {
  const label = <PlatformChip platform={account.platform} label={account.platform.toUpperCase()} />;
  if (account.platform !== "max") return label;
  return (
    <details data-testid="native-id-editor" className="min-w-28 [&_form]:mt-3 [&_form]:grid [&_form]:gap-2 [&_summary]:cursor-pointer">
      <summary aria-label="Изменить chat_id MAX">{label}</summary>
      <form method="post" action={`/manage/platform-accounts/${account.legacyId}/native-id`}>
        <Label className="grid gap-1.5 text-sm leading-normal font-normal">chat_id
          <Input name="native_id" defaultValue={account.nativeId ?? ""} required disabled={!canEdit} /></Label>
        {fields(csrf, account.rowVersion)}
        <Button type="submit" disabled={!canEdit}>Сохранить</Button>
      </form>
    </details>
  );
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

/** Таблица аккаунтов: прокрутка внутри карточки, заголовок закреплён. */
export function AccountsTable({ institutions, status, csrf, canEdit, canDelete }: {
  institutions: ManagedInstitution[]; status: CatalogStatus | null; csrf: string; canEdit: boolean; canDelete: boolean;
}) {
  return (
    <div data-testid="platform-table-scroll"
      className="bg-card max-h-[70vh] min-w-0 overflow-auto overscroll-contain rounded-lg border [&_[data-slot=table-container]]:overflow-visible [&_small]:text-muted-foreground [&_small]:mt-1 [&_small]:block [&_td]:align-top [&_td]:whitespace-normal">
      <Table data-testid="platform-table">
        <TableHeader className="bg-card sticky top-0 z-20 shadow-[inset_0_-1px_0_var(--border)] [&_tr]:border-0">
          <TableRow className="hover:bg-transparent">
            <TableHead>Вуз</TableHead>
            <TableHead>Платформа</TableHead>
            <TableHead>Аккаунт</TableHead>
            <TableHead>Данные</TableHead>
            <TableHead>Статус</TableHead>
            <TableHead className="text-right"><span className="sr-only">Действия</span></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {institutions.flatMap((institution) => institution.accounts.length
            ? institution.accounts.map((account, index) => (
              <TableRow key={account.id}>
                {index === 0 ? <InstitutionCell institution={institution} csrf={csrf} canEdit={canEdit} /> : null}
                <TableCell><PlatformLabel account={account} csrf={csrf} canEdit={canEdit} /></TableCell>
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
              </TableRow>
            ))
            : [<TableRow key={institution.id}>
              <InstitutionCell institution={institution} csrf={csrf} canEdit={canEdit} withRating={false} />
              <TableCell colSpan={5} className="text-muted-foreground">Аккаунты ещё не привязаны</TableCell>
            </TableRow>])}
        </TableBody>
      </Table>
    </div>
  );
}
