import { CompareDashboardSkeleton } from "@/components/compare/compare-skeleton";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui";
import {
  FILTER_CONTROL_CLASS,
  FILTER_PLATFORM_CLASS,
  FILTER_SEARCH_CLASS,
  FILTER_TOOLBAR_CLASS,
} from "@/components/filter-toolbar";

/**
 * Шапка страницы и полоса фильтров при переходе.
 *
 * Заголовок и описание не зависят от данных, которых мы ждём, поэтому их
 * незачем прятать: они известны по адресу, куда идём, и появляются сразу.
 * Пустыми остаются только сами поля — их состояние приедет с адресом.
 */
function Chrome({ title, description, controls = 3 }: {
  title: string; description: string; controls?: number;
}) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <div className={FILTER_TOOLBAR_CLASS}>
        <div className={FILTER_SEARCH_CLASS}>
          <Skeleton className="h-9 min-w-0 flex-1" />
          <Skeleton className="size-9 shrink-0" />
        </div>
        {Array.from({ length: controls }, (_, index) => (
          <div key={index} className={FILTER_CONTROL_CLASS}><Skeleton className="h-9 w-full" /></div>
        ))}
        <div className={FILTER_PLATFORM_CLASS}><Skeleton className="h-9 w-full max-w-[21rem]" /></div>
      </div>
    </>
  );
}

/** Одна карточка вуза: та же высота и та же внутренняя разбивка, что у
 *  настоящей, поэтому подмена не двигает сетку. */
function CardShape() {
  return (
    <div className="bg-card flex min-h-[470px] flex-col gap-4 rounded-xl border p-5 pt-6 shadow-sm">
      <Skeleton className="h-5 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
      <div className="flex gap-1.5">
        <Skeleton className="h-6 w-12" /><Skeleton className="h-6 w-12" /><Skeleton className="h-6 w-12" />
      </div>
      <Skeleton className="h-1.5 w-full" />
      {/* Четыре числа в две колонки, под каждым подпись и место под плашку
          изменения — ровно как в настоящей карточке. */}
      <div className="my-4 grid flex-1 grid-cols-2 content-center gap-x-5 gap-y-3">
        {Array.from({ length: 4 }, (_, cell) => (
          <div key={cell} className="grid gap-1.5">
            <Skeleton className="h-7 w-16" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-[22px] w-14" />
          </div>
        ))}
      </div>
      <div className="mt-auto grid gap-2 border-t pt-3.5">
        <Skeleton className="h-4 w-24" /><Skeleton className="h-3 w-2/3" />
      </div>
    </div>
  );
}

/** Сетка карточек вуза вместе с шапкой обзора. */
export function CardGridSkeleton({ count = 8, chrome = true }: { count?: number; chrome?: boolean }) {
  return (
    <>
      {chrome ? <Chrome title="Обзор каналов"
        description="Прирост показателей всех постов в базе за выбранный период, а не только новых." /> : null}
      <div className="reveal grid grid-cols-[repeat(auto-fill,minmax(270px,1fr))] gap-4"
        role="status" aria-live="polite">
        <span className="sr-only">Загрузка карточек</span>
        {Array.from({ length: count }, (_, index) => <CardShape key={index} />)}
      </div>
    </>
  );
}

/** Универсальная таблица для экранов, которые и на мобильном остаются
 *  таблицами (сравнение и служебные списки). */
export function TableSkeleton({ rows = 10, chrome = true }: { rows?: number; chrome?: boolean }) {
  return (
    <>
      {chrome ? <Chrome title="Статистика публикаций"
        description="Накопленные результаты публикаций, вышедших в выбранный период."
        controls={3} /> : null}
      <div className="bg-card rounded-xl border p-5 shadow-sm" role="status" aria-live="polite">
        <span className="sr-only">Загрузка таблицы</span>
        <Skeleton className="h-5 w-40" />
        <div className="reveal mt-5 grid gap-3">
          {Array.from({ length: rows }, (_, index) => <Skeleton key={index} className="h-8 w-full" />)}
        </div>
      </div>
    </>
  );
}

/** Статистика меняет представление в том же breakpoint, что и результат:
 *  строки на широком экране и полноценные карточки на телефоне. Старая
 *  заготовка всегда обещала таблицу, а затем резко меняла и ширину, и высоту. */
export function StatisticsSkeleton({ rows = 5, chrome = true, view = "publications" }: {
  rows?: number;
  chrome?: boolean;
  view?: "publications" | "entities";
}) {
  return (
    <>
      {chrome ? <Chrome title="Статистика публикаций"
        description="Накопленные результаты публикаций, вышедших в выбранный период."
        controls={3} /> : null}
      <section className="min-w-0 space-y-3" role="status" aria-live="polite">
        <span className="sr-only">Загрузка статистики</span>
        <Skeleton className="h-6 w-44" />
        <div className="grid min-w-0 gap-3 md:hidden">
          {Array.from({ length: Math.min(rows, 5) }, (_, index) => (
            <div key={index} className="min-w-0 rounded-xl border bg-card p-4 shadow-sm">
              <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="min-w-0 flex-1 space-y-2">
                  <Skeleton className="h-3 w-7" />
                  <Skeleton className="h-5 w-32 max-w-full" />
                  <Skeleton className="h-3 w-full" />
                  <Skeleton className="h-3 w-4/5" />
                </div>
                <div className="grid shrink-0 justify-items-end gap-1">
                  <Skeleton className="h-6 w-16" />
                  <Skeleton className="h-3 w-10" />
                </div>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2">
                {Array.from({ length: 3 }, (_, metric) => (
                  <div key={metric} className="grid min-w-0 gap-1">
                    <Skeleton className="h-3 w-4/5" />
                    <Skeleton className="h-5 w-3/5" />
                  </div>
                ))}
              </div>
              <div className="mt-4 flex gap-2">
                <Skeleton className="h-9 min-w-0 flex-1" />
                {view === "publications" ? <Skeleton className="size-9 shrink-0" /> : null}
              </div>
            </div>
          ))}
        </div>
        <div className="hidden rounded-xl border bg-card p-5 shadow-sm md:block">
          <div className="grid gap-3">
            {Array.from({ length: rows }, (_, index) => <Skeleton key={index} className="h-8 w-full" />)}
          </div>
        </div>
      </section>
    </>
  );
}

/** Публикация: карточка сигнала, два графика и таблица замеров. */
export function PublicationSkeleton() {
  return (
    <div className="grid gap-4" role="status" aria-live="polite">
      <span className="sr-only">Загрузка публикации</span>
      <Skeleton className="h-9 w-80 max-w-full" />
      <div className="flex gap-2"><Skeleton className="h-10 w-36" /><Skeleton className="h-10 w-36" /></div>
      <div className="bg-card grid gap-3 rounded-xl border p-5 shadow-sm">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-4 w-full max-w-xl" />
        <Skeleton className="h-4 w-3/4 max-w-lg" />
      </div>
      <div className="grid gap-4">
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
        <div className="reveal grid gap-3">
          {Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="h-8 w-full" />)}
        </div>
      </div>
    </div>
  );
}

/**
 * Страница площадки: заголовок, переключатель площадок, шесть плиток рядом с
 * графиком и таблица публикаций.
 *
 * Раскладка повторяет настоящую: слева две колонки по три плитки, справа
 * график во всю высоту блока. Прежняя заготовка рисовала шесть одинаковых
 * полос и широкий блок под ними — при подмене страница подпрыгивала.
 */
export function AccountSkeleton({ chrome = true }: { chrome?: boolean }) {
  return (
    <div className="grid gap-5" role="status" aria-live="polite">
      <span className="sr-only">Загрузка данных площадки</span>
      {chrome ? <>
        <Skeleton className="mb-1 h-9 w-96 max-w-full" />
        <div className="flex flex-wrap gap-2">
          {Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-10 w-44" />)}
        </div>
      </> : null}
      <div className="bg-card grid gap-4 rounded-xl border p-5 shadow-sm">
        <Skeleton className="h-4 w-full max-w-3xl" />
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="grid gap-3 sm:grid-cols-2">
            {Array.from({ length: 6 }, (_, index) => (
              <div key={index} className="grid content-start gap-1 rounded-lg border p-4">
                <Skeleton className="h-6 w-20" />
                <Skeleton className="h-4 w-28" />
                <Skeleton className="mt-1 h-[22px] w-14" />
              </div>
            ))}
          </div>
          <Skeleton className="h-[380px] w-full rounded-lg" />
        </div>
      </div>
      <div className="bg-card grid gap-3 rounded-xl border p-5 shadow-sm">
        <div className="reveal grid gap-3">
          {Array.from({ length: 10 }, (_, index) => <Skeleton key={index} className="h-8 w-full" />)}
        </div>
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
  if (path.startsWith("/statistics")) {
    const view = new URL(href, "https://m-ranked.invalid").searchParams.get("view") === "entities" ? "entities" : "publications";
    return <StatisticsSkeleton view={view} />;
  }
  if (path.startsWith("/compare")) {
    return <CompareDashboardSkeleton />;
  }
  if (/^\/(accounts|channels|platform-accounts|institutions)\//.test(path)) return <AccountSkeleton />;
  if (/^\/(publications|posts|platform-posts)\//.test(path)) return <PublicationSkeleton />;
  return null;
}
