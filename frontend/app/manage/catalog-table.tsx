"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import {
  ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Pause, Play, Search, Trash2, X,
} from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

const DeleteDialog = dynamic(() => import("@/components/catalog-delete-dialog"), { ssr: false });

export type AccountState = "ok" | "off" | "attention";
export type CatalogAccountRow = {
  id: string; legacyId: number; rowVersion: number; enabled: boolean; platform: string; state: AccountState;
  search: string; cells: ReactNode;
};
export type CatalogGroup = { id: string; search: string; header: ReactNode; accounts: CatalogAccountRow[] };

const PLATFORMS = [["all", "Все площадки"], ["telegram", "Telegram"], ["vk", "VK"], ["max", "MAX"], ["rutube", "Rutube"]] as const;
const STATES = [["all", "Любой статус"], ["ok", "Работает"], ["attention", "Требует внимания"], ["off", "Отключён"]] as const;
const PAGE_SIZES = [10, 20, 50, 100] as const;
const CODES: Record<string, string> = {
  conflict: "данные уже изменились", forbidden: "недостаточно прав", invalid: "некорректный запрос",
  "not-found": "аккаунт не найден", unavailable: "сервис недоступен", failed: "не удалось сохранить",
};

type Selection = { selected: ReadonlySet<string>; toggle: (ids: string[], on: boolean) => void };
const SelectionContext = createContext<Selection>({ selected: new Set(), toggle: () => undefined });

function plural(value: number, one: string, few: string, many: string) {
  const n = Math.abs(value) % 100;
  return n > 10 && n < 20 ? many : n % 10 === 1 ? one : n % 10 >= 2 && n % 10 <= 4 ? few : many;
}

/** Чекбокс группы строк: отмечен, если отмечены все, «частично» — если часть. */
function GroupCheckbox({ ids, label, className }: { ids: string[]; label: string; className?: string }) {
  const { selected, toggle } = useContext(SelectionContext);
  const count = ids.filter((id) => selected.has(id)).length;
  return <Checkbox aria-label={label} className={className} disabled={!ids.length}
    checked={ids.length > 0 && count === ids.length} indeterminate={count > 0 && count < ids.length}
    onCheckedChange={(on) => toggle(ids, on)} />;
}

type Outcome = { done: number; skipped: number; errors: string[] };

/**
 * Таблица вузов и аккаунтов в духе data-table shadcn: поиск, фильтры площадки
 * и статуса, страницы по вузам (аккаунты вуза не разрываются между
 * страницами), выбор строк и массовые действия.
 *
 * Ячейки строк рисует сервер: формы с CSRF и кодом операции остаются
 * обычными HTML-формами. Массовые действия идут той же дорогой, что и формы,
 * — через фасад /manage, по одной команде на аккаунт с ожидаемой версией
 * строки; фасад отвечает им JSON вместо перехода.
 */
export function CatalogDataTable({ groups, csrf, canEdit, canDelete }: {
  groups: CatalogGroup[]; csrf: string; canEdit: boolean; canDelete: boolean;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState("all");
  const [state, setState] = useState("all");
  const [pageSize, setPageSize] = useState<number>(10);
  const [page, setPage] = useState(0);
  const [picked, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [running, setRunning] = useState<{ done: number; total: number } | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const accounts = useMemo(() => new Map(groups.flatMap((group) => group.accounts.map((account) => [account.id, account]))), [groups]);
  const total = accounts.size;

  // Обновление данных (живое или после команды) могло удалить аккаунты: в выборе остаются только живые.
  const selected = useMemo<ReadonlySet<string>>(() => new Set([...picked].filter((id) => accounts.has(id))), [picked, accounts]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtering = needle !== "" || platform !== "all" || state !== "all";
    return groups.flatMap((group) => {
      const groupMatches = !needle || group.search.includes(needle);
      const rows = group.accounts.filter((account) =>
        (platform === "all" || account.platform === platform)
        && (state === "all" || account.state === state)
        && (groupMatches || account.search.includes(needle)));
      if (!rows.length && (filtering || group.accounts.length)) return [];
      return [{ ...group, rows }];
    });
  }, [groups, query, platform, state]);

  const filtering = query.trim() !== "" || platform !== "all" || state !== "all";
  const pages = Math.max(1, Math.ceil(visible.length / pageSize));
  const current = Math.min(page, pages - 1);
  const shown = visible.slice(current * pageSize, (current + 1) * pageSize);
  const shownIds = shown.flatMap((group) => group.rows.map((row) => row.id));
  const visibleAccounts = visible.reduce((sum, group) => sum + group.rows.length, 0);

  const selection = useMemo<Selection>(() => ({
    selected,
    toggle: (ids, on) => setSelected((previous) => {
      const next = new Set(previous);
      for (const id of ids) if (on) next.add(id); else next.delete(id);
      return next;
    }),
  }), [selected]);

  const reset = (apply: () => void) => { apply(); setPage(0); };

  async function run(action: "disable" | "enable" | "delete") {
    const targets = [...selected].map((id) => accounts.get(id)).filter((row): row is CatalogAccountRow => !!row);
    const work = targets.filter((row) => action === "delete" || (action === "disable" ? row.enabled : !row.enabled));
    const result: Outcome = { done: 0, skipped: targets.length - work.length, errors: [] };
    setOutcome(null);
    setRunning({ done: 0, total: work.length });
    for (const [index, row] of work.entries()) {
      const body = new URLSearchParams({ csrf_token: csrf, expected_row_version: String(row.rowVersion), correlation_id: crypto.randomUUID() });
      try {
        const response = await fetch(`/manage/platform-accounts/${row.legacyId}/${action}`, {
          method: "POST", body, credentials: "same-origin", cache: "no-store",
          headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Mranked-Response": "json", Accept: "application/json" },
        });
        const payload = await response.json().catch(() => null) as { location?: string; detail?: unknown } | null;
        const location = new URL(payload?.location ?? "/manage", window.location.origin);
        if (location.searchParams.get("sign_in") === "failed") { setRunning(null); router.refresh(); return; }
        const code = location.searchParams.get("command_error");
        if (!response.ok || code) result.errors.push(`${row.platform.toUpperCase()} #${row.legacyId}: ${CODES[code ?? ""] ?? `ошибка ${response.status}`}`);
        else result.done += 1;
      } catch {
        result.errors.push(`${row.platform.toUpperCase()} #${row.legacyId}: сеть недоступна`);
      }
      setRunning({ done: index + 1, total: work.length });
    }
    setRunning(null);
    setOutcome(result);
    if (result.done) setSelected(new Set());
    router.refresh();
  }

  const busy = running !== null;
  return (
    <SelectionContext.Provider value={selection}>
      <div className="mb-3 flex flex-wrap items-center gap-2" data-testid="catalog-toolbar">
        <div className="relative w-full sm:w-72">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden="true" />
          <Input type="search" value={query} onChange={(event) => reset(() => setQuery(event.target.value))}
            placeholder="Вуз, канал или имя аккаунта" aria-label="Поиск по вузам и аккаунтам" className="h-8 pl-8 text-sm md:text-sm" />
        </div>
        <NativeSelect aria-label="Площадка" value={platform} onChange={(event) => reset(() => setPlatform(event.target.value))} className="h-8">
          {PLATFORMS.map(([value, label]) => <NativeSelectOption key={value} value={value}>{label}</NativeSelectOption>)}
        </NativeSelect>
        <NativeSelect aria-label="Статус" value={state} onChange={(event) => reset(() => setState(event.target.value))} className="h-8">
          {STATES.map(([value, label]) => <NativeSelectOption key={value} value={value}>{label}</NativeSelectOption>)}
        </NativeSelect>
        {filtering ? (
          <Button variant="ghost" size="sm" className="h-8" onClick={() => reset(() => { setQuery(""); setPlatform("all"); setState("all"); })}>
            <X data-icon="inline-start" aria-hidden="true" />Сбросить
          </Button>
        ) : null}
        {filtering ? <span className="text-muted-foreground ml-auto text-xs tabular-nums" role="status">
          Найдено: {visibleAccounts} {plural(visibleAccounts, "аккаунт", "аккаунта", "аккаунтов")} · {visible.length} {plural(visible.length, "вуз", "вуза", "вузов")}
        </span> : null}
      </div>

      {selected.size ? (
        <div className="bg-muted/60 mb-3 flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-sm" data-testid="bulk-actions" aria-busy={busy}>
          <span className="font-medium tabular-nums">Выбрано {selected.size}</span>
          <span className="text-muted-foreground text-xs">{running ? `выполняется ${running.done} из ${running.total}…` : "действие применится к каждому аккаунту"}</span>
          <div className="ml-auto flex flex-wrap gap-2">
            <Button variant="outline" size="sm" disabled={!canEdit || busy} onClick={() => void run("disable")}>
              <Pause data-icon="inline-start" aria-hidden="true" />Остановить сбор
            </Button>
            <Button variant="outline" size="sm" disabled={!canEdit || busy} onClick={() => void run("enable")}>
              <Play data-icon="inline-start" aria-hidden="true" />Возобновить сбор
            </Button>
            <Button variant="destructive" size="sm" disabled={!canDelete || busy} title={canDelete ? undefined : "Доступно роли ADMIN"} onClick={() => setConfirmDelete(true)}>
              <Trash2 data-icon="inline-start" aria-hidden="true" />Удалить
            </Button>
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => setSelected(new Set())}>Снять выбор</Button>
          </div>
        </div>
      ) : null}
      {confirmDelete ? <DeleteDialog onCancel={() => setConfirmDelete(false)} onConfirm={() => { setConfirmDelete(false); void run("delete"); }} /> : null}
      {outcome ? (
        <Alert role="status" className={cn("mb-3 p-3 text-sm", outcome.errors.length ? "border-warning/30 bg-warning/10 text-warning" : "border-success/30 bg-success/10 text-success")}>
          Готово: {outcome.done}{outcome.skipped ? `, уже в нужном состоянии: ${outcome.skipped}` : ""}{outcome.errors.length ? `, с ошибкой: ${outcome.errors.length} — ${outcome.errors.slice(0, 5).join("; ")}${outcome.errors.length > 5 ? "…" : ""}` : ""}.
        </Alert>
      ) : null}

      <div data-testid="platform-table-scroll" className="bg-card max-h-[70vh] min-w-0 overflow-auto overscroll-contain rounded-lg border [&_small]:text-muted-foreground [&_small]:mt-1 [&_small]:block [&_td]:align-top [&_td]:whitespace-normal">
        <Table data-testid="platform-table" frame={false} containerProps={{ className: "overflow-visible" }}>
          <TableHeader className="bg-muted sticky top-0 z-20 shadow-[inset_0_-1px_0_var(--border)] [&_tr]:border-0">
            <TableRow>
              <TableHead className="w-10"><GroupCheckbox ids={shownIds} label="Выбрать все аккаунты на странице" /></TableHead>
              <TableHead>Вуз</TableHead>
              <TableHead>Платформа</TableHead>
              <TableHead>Аккаунт</TableHead>
              <TableHead>Данные</TableHead>
              <TableHead>Статус</TableHead>
              <TableHead className="text-right"><span className="sr-only">Действия</span></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.length ? shown.flatMap((group) => group.rows.length
              ? group.rows.map((row, index) => (
                <TableRow key={row.id} data-state={selected.has(row.id) ? "selected" : undefined}>
                  <TableCell><GroupCheckbox ids={[row.id]} label="Выбрать аккаунт" className="mt-0.5" /></TableCell>
                  {index === 0 ? (
                    <TableCell rowSpan={group.rows.length} className="bg-card min-w-56 space-y-1 border-r align-top">
                      <div className="flex items-start gap-2">
                        <GroupCheckbox ids={group.rows.map((item) => item.id)} label="Выбрать все аккаунты вуза" className="mt-0.5" />
                        <div className="min-w-0 space-y-1">{group.header}</div>
                      </div>
                    </TableCell>
                  ) : null}
                  {row.cells}
                </TableRow>
              ))
              : [<TableRow key={group.id}>
                <TableCell />
                <TableCell className="bg-card min-w-56 space-y-1 border-r align-top">{group.header}</TableCell>
                <TableCell colSpan={5} className="text-muted-foreground">Аккаунты ещё не привязаны</TableCell>
              </TableRow>])
              : <TableRow><TableCell colSpan={7} className="text-muted-foreground h-24 text-center">Ничего не найдено. Измените запрос или фильтры.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm" data-testid="catalog-pagination">
        <p className="text-muted-foreground text-xs tabular-nums">Выбрано {selected.size} из {total} {plural(total, "аккаунта", "аккаунтов", "аккаунтов")}.</p>
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-xs font-medium">Вузов на странице
            <NativeSelect value={String(pageSize)} onChange={(event) => reset(() => setPageSize(Number(event.target.value)))} className="h-8 w-20">
              {PAGE_SIZES.map((size) => <NativeSelectOption key={size} value={String(size)}>{size}</NativeSelectOption>)}
            </NativeSelect>
          </label>
          <span className="text-xs font-medium tabular-nums">Страница {current + 1} из {pages}</span>
          <div className="flex items-center gap-1">
            <Button variant="outline" size="icon" className="size-8" aria-label="Первая страница" disabled={current === 0} onClick={() => setPage(0)}><ChevronsLeft aria-hidden="true" /></Button>
            <Button variant="outline" size="icon" className="size-8" aria-label="Предыдущая страница" disabled={current === 0} onClick={() => setPage(current - 1)}><ChevronLeft aria-hidden="true" /></Button>
            <Button variant="outline" size="icon" className="size-8" aria-label="Следующая страница" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}><ChevronRight aria-hidden="true" /></Button>
            <Button variant="outline" size="icon" className="size-8" aria-label="Последняя страница" disabled={current >= pages - 1} onClick={() => setPage(pages - 1)}><ChevronsRight aria-hidden="true" /></Button>
          </div>
        </div>
      </div>
    </SelectionContext.Provider>
  );
}
