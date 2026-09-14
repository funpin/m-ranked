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
