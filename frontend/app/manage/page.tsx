import type { Metadata } from "next";
import { headers } from "next/headers";
import { Activity, LayoutList, Server, Users } from "lucide-react";
import Link from "@/components/native-link";
import { Card } from "@/components/ui/card";
import { CatalogApiError, catalogReader } from "@/lib/catalog-api";
import { first, type SearchParams } from "@/lib/params";
import { cn } from "@/lib/utils";
import { AdminLogin, AdminSignOut } from "./admin-access";
import { LiveRefresh } from "./live-refresh";
import { ChannelsTab } from "./channels";
import { plural } from "./shared";
import { ServersTab } from "./servers";
import { SystemTab, type SystemRange } from "./system";
import { VisitorsTab } from "./visitors";
import { PageTitle } from "@/components/page-title";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const metadata: Metadata = {
  title: "Управление",
  description: "Закрытое управление вузами, официальными аккаунтами и сбором данных.",
  referrer: "same-origin",
  robots: { index: false, follow: false, nocache: true },
};

const statuses: Record<string, string> = {
  "institution-added": "Вуз добавлен.", "institution-updated": "Названия вуза обновлены.", "account-added": "Аккаунты сохранены.",
  "accounts-updated": "Аккаунты сохранены.", "account-disabled": "Сбор для аккаунта остановлен. История сохранена.",
  "account-enabled": "Сбор для аккаунта включён.", "native-id-updated": "Идентификатор площадки сохранён.",
  "account-deleted": "Аккаунт и собранные по нему данные удалены.",
};
const commandErrors: Record<string, string> = {
  conflict: "Данные уже изменились. Проверьте актуальные значения и повторите действие.", forbidden: "Недостаточно прав для этого действия.",
  invalid: "Проверьте заполненные поля и повторите действие.", "not-found": "Вуз или аккаунт больше не существует.",
  unavailable: "Сервис управления временно недоступен. Проверьте данные перед повторной отправкой.", failed: "Не удалось сохранить изменение.",
};

const TABS = [
  { id: "channels", label: "Каналы", title: "Управление каналами", description: "Добавляйте, временно отключайте или полностью удаляйте мониторинг каналов.", icon: LayoutList },
  { id: "visitors", label: "Посетители", title: "Посетители сайта", description: "Уникальные посетители без cookie: кто на сайте сейчас и как меняется посещаемость.", icon: Users },
  { id: "system", label: "Система", title: "Состояние системы", description: "CPU, RAM, диск и сеть — вживую каждые 5 секунд; сбор, анализ, трафик и хранилище — по снимкам сервера раз в минуту.", icon: Activity },
  { id: "servers", label: "Серверы", title: "Серверы и хранение", description: "Серверы-сборщики и место на дисках, политики сбора, хранения и анализа, резервные копии и холодный архив.", icon: Server },
] as const;
type Tab = (typeof TABS)[number]["id"];
// Момент отрисовки для подписей «N мин назад»: страница динамическая и
// рисуется на каждый запрос, так что «сейчас» здесь и есть время ответа.
const renderedAt = () => Date.now();

function ManageTabs({ active }: { active: Tab }) {
  return (
    <nav aria-label="Разделы управления" className="bg-muted mb-6 inline-flex max-w-full overflow-x-auto rounded-lg p-[3px]">
      {TABS.map(({ id, label, icon: Icon }) => (
        <Link key={id} href={id === "channels" ? "/manage" : `/manage?tab=${id}`} prefetch={false} aria-current={id === active ? "page" : undefined}
          className={cn("inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap no-underline transition-colors",
            id === active ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
          <Icon className="size-4" aria-hidden="true" />{label}
        </Link>
      ))}
    </nav>
  );
}

export default async function ManagePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const incoming = new Headers(await headers()), query = await searchParams;
  const csrf = incoming.get("x-mranked-csrf") ?? "";
  const canEdit = ["1", "true"].includes(incoming.get("x-mranked-can-edit") ?? "") && !!csrf;
  const canDelete = ["1", "true"].includes(incoming.get("x-mranked-can-delete") ?? "") && !!csrf;
  // Без сессии страница показывает форму входа, а не окно Basic-аутентификации.
  if (incoming.get("x-mranked-signed-in") !== "true") return <AdminLogin failed={first(query.sign_in) === "failed"} />;
  const requested = first(query.tab);
  const tab: Tab = TABS.some((item) => item.id === requested) ? requested as Tab : "channels";
  const meta = TABS.find((item) => item.id === tab)!;
  const reader = catalogReader(incoming);
  const now = renderedAt();
  // Каждая вкладка читает только своё: панель не ходит в API за чужими данными.
  const header = (count?: number) => (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="font-heading text-2xl font-semibold tracking-tight sm:text-3xl"><PageTitle text={meta.title} /></h1>
        <p className="text-muted-foreground mt-2 text-sm">{meta.description}</p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {/* Мониторинг — каждые 15 с, каталог — каждые 30 с. */}
        <LiveRefresh intervalMs={tab === "channels" ? 30_000 : 15_000} />
        {count !== undefined ? <div className="bg-muted flex items-baseline gap-2 rounded-full px-4 py-2 text-xs [&>b]:text-lg">
          <b>{count}</b><span>{plural(count, "канал добавлен", "канала добавлено", "каналов добавлено")}</span>
        </div> : null}
        <AdminSignOut csrf={csrf} />
      </div>
    </div>
  );

  if (tab === "visitors") {
    const range = first(query.range) === "month" ? "month" : "week";
    const visitors = await reader.visitors(range).catch(() => null);
    return <>{header()}<ManageTabs active={tab} /><VisitorsTab visitors={visitors} range={range} /></>;
  }
  if (tab === "system") {
    const requested = first(query.range);
    const range: SystemRange = requested === "1h" || requested === "3h" || requested === "week" ? requested : "day";
    const [overview, status] = await Promise.all([reader.system(range).catch(() => null), reader.status().catch(() => null)]);
    return <>{header()}<ManageTabs active={tab} /><SystemTab overview={overview} status={status} range={range} now={now} csrf={csrf} canRefreshBackup={canDelete} backupOutcome={first(query.backup_status)} /></>;
  }

  if (tab === "servers") {
    const storage = await reader.storage().catch(() => null);
    return <>{header()}<ManageTabs active={tab} /><ServersTab overview={storage} csrf={csrf} canEdit={canDelete} now={now}
      status={first(query.storage_status)} error={first(query.storage_error)} /></>;
  }

  const [catalogResult, statusResult] = await Promise.allSettled([reader.institutions(), reader.status()]);
  if (catalogResult.status === "rejected") return <>
    {header()}<ManageTabs active={tab} />
    <Card className="block p-5 text-sm" role="alert">
      <p>{catalogResult.reason instanceof CatalogApiError ? catalogResult.reason.message : "Не удалось загрузить каталог."}</p>
      <Link href="/manage" prefetch={false}>Повторить загрузку</Link>
    </Card>
  </>;
  // SQLite NOCASE folds ASCII only; preserve the legacy catalog ordering.
  const fold = (name: string) => name.replace(/[A-Z]/g, (letter) => letter.toLowerCase());
  const institutions = catalogResult.value.sort((a, b) => fold(a.name) < fold(b.name) ? -1 : fold(a.name) > fold(b.name) ? 1 : a.legacyId - b.legacyId);
  // Bounded API pages use IDs; presentation follows SQLite's platform/title/username order.
  const textOrder = (a: string | null, b: string | null) => a === b ? 0 : a === null ? -1 : b === null ? 1 : a < b ? -1 : 1;
  for (const institution of institutions) institution.accounts.sort((a, b) => textOrder(a.platform, b.platform) || textOrder(a.title, b.title) || textOrder(a.username, b.username) || a.legacyId - b.legacyId);
  const status = statusResult.status === "fulfilled" ? statusResult.value : null;
  const channelCount = status?.channelCount ?? institutions.flatMap((row) => row.accounts).filter((row) => row.channelId !== null).length;
  const selected = Number(first(query.institution_id));
  const selectedId = institutions.some((row) => row.legacyId === selected) ? selected : institutions[0]?.legacyId ?? null;
  return <>
    {header(channelCount)}
    <ManageTabs active={tab} />
    <ChannelsTab institutions={institutions} status={status} selectedId={selectedId} csrf={csrf} canEdit={canEdit} canDelete={canDelete}
      message={statuses[first(query.platform_status) ?? ""]} commandError={commandErrors[first(query.command_error) ?? ""]}
      correlation={first(query.correlation_id) ?? ""} ratingOutcome={first(query.m_rating_status)} />
  </>;
}
