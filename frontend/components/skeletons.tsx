import { Skeleton } from "@/components/ui/skeleton";

/** Сетка карточек вуза: те же размеры, что у настоящих, поэтому подмена не
 *  двигает страницу. */
export function CardGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(270px,1fr))] gap-4" role="status" aria-live="polite">
      <span className="sr-only">Загрузка карточек</span>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="bg-card flex min-h-[470px] flex-col gap-4 rounded-xl border p-5 pt-6 shadow-sm">
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
          <div className="flex gap-1.5">
            <Skeleton className="h-6 w-12" /><Skeleton className="h-6 w-12" /><Skeleton className="h-6 w-12" />
          </div>
          <Skeleton className="h-1.5 w-full" />
          <div className="mt-2 grid grid-cols-2 gap-x-5 gap-y-6">
            {Array.from({ length: 4 }, (_, cell) => (
              <div key={cell} className="grid gap-2"><Skeleton className="h-7 w-16" /><Skeleton className="h-3 w-full" /></div>
            ))}
          </div>
          <Skeleton className="mt-auto h-4 w-2/3" />
        </div>
      ))}
    </div>
  );
}

/** Таблица: шапка и строки постоянной высоты. */
export function TableSkeleton({ rows = 10 }: { rows?: number }) {
  return (
    <div className="bg-card rounded-xl border p-5 shadow-sm" role="status" aria-live="polite">
      <span className="sr-only">Загрузка таблицы</span>
      <Skeleton className="h-5 w-40" />
      <div className="mt-5 grid gap-3">
        {Array.from({ length: rows }, (_, index) => <Skeleton key={index} className="h-8 w-full" />)}
      </div>
    </div>
  );
}

/** Публикация: карточка сигнала, два графика и таблица замеров. Высоты те же,
 *  что у настоящих блоков, поэтому подмена не дёргает страницу. */
export function PublicationSkeleton() {
  return (
    <div className="grid gap-4" role="status" aria-live="polite">
      <span className="sr-only">Загрузка публикации</span>
      <div className="bg-card grid gap-3 rounded-xl border p-5 shadow-sm">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-4 w-full max-w-xl" />
        <Skeleton className="h-4 w-3/4 max-w-lg" />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        {Array.from({ length: 2 }, (_, index) => (
          <div key={index} className="bg-card grid gap-4 rounded-xl border p-5 shadow-sm">
            <Skeleton className="h-5 w-56" />
            <div className="flex gap-2"><Skeleton className="h-8 w-36" /><Skeleton className="h-8 w-40" /><Skeleton className="h-8 w-44" /></div>
            <Skeleton className="h-[360px] w-full" />
          </div>
        ))}
      </div>
      <div className="bg-card grid gap-3 rounded-xl border p-5 shadow-sm">
        <Skeleton className="h-5 w-44" />
        {Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="h-8 w-full" />)}
      </div>
    </div>
  );
}

/** Страница вуза: плитки со сводкой, недельная полоса и таблица публикаций. */
export function AccountSkeleton() {
  return (
    <div className="grid gap-5" role="status" aria-live="polite">
      <span className="sr-only">Загрузка данных площадки</span>
      <div className="bg-card grid gap-4 rounded-xl border p-5 shadow-sm">
        <Skeleton className="h-4 w-full max-w-3xl" />
        <div className="grid gap-3 sm:grid-cols-[1.6fr_1fr]">
          {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-20 w-full" />)}
        </div>
        <Skeleton className="h-32 w-full" />
      </div>
      <div className="bg-card grid gap-3 rounded-xl border p-5 shadow-sm">
        {Array.from({ length: 10 }, (_, index) => <Skeleton key={index} className="h-8 w-full" />)}
      </div>
    </div>
  );
}

/** Заготовка страницы, на которую уходит переход.
 *
 *  Раскладки маршрутов различаются, и показывать при уходе на рейтинг сетку
 *  карточек обзора значит обещать не то, что появится. Возвращает null для
 *  перехода внутри текущего маршрута — там уместна заготовка самой страницы.
 */
export function skeletonFor(href: string) {
  if (!href) return null;
  const path = href.split("?")[0] ?? "";
  if (path === "/" ) return <CardGridSkeleton />;
  if (path.startsWith("/rating") || path.startsWith("/compare")) return <TableSkeleton />;
  if (/^\/(accounts|channels|platform-accounts|institutions)\//.test(path)) return <AccountSkeleton />;
  if (/^\/(publications|posts|platform-posts)\//.test(path)) return <PublicationSkeleton />;
  return null;
}
