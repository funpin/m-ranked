import { Skeleton } from "@/components/ui/skeleton";

export function LoadingState() {
  return <div className="grid gap-5" role="status" aria-live="polite">
    <span className="sr-only">Загрузка данных</span>
    <Skeleton className="h-9 w-2/3 max-w-md" />
    <Skeleton className="h-5 w-full max-w-xl" />
    <Skeleton className="h-28 w-full" />
    <div className="grid gap-4 md:grid-cols-3">
      {Array.from({ length: 3 }, (_, index) => <Skeleton key={index} className="h-52 w-full" />)}
    </div>
  </div>;
}
