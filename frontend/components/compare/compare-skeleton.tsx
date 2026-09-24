import { Skeleton } from "@/components/ui/skeleton";

/** Каркас панели сравнения, пока данные в пути: те же размеры, чтобы
 *  приход данных не сдвигал страницу. */
export function CompareDashboardSkeleton() {
  return (
    <div className="grid gap-8" role="status" aria-busy="true" aria-label="Панель сравнения загружается" data-testid="compare-skeleton">
      <Skeleton className="h-[92px] w-full rounded-xl" />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-[118px] rounded-xl" />)}
      </div>
      <Skeleton className="h-[520px] w-full rounded-xl" />
      <div className="grid gap-4 xl:grid-cols-5">
        <Skeleton className="h-[440px] rounded-xl xl:col-span-3" />
        <Skeleton className="h-[440px] rounded-xl xl:col-span-2" />
      </div>
    </div>
  );
}
