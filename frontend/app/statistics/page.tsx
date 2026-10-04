import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { ArrowRight, Search, X } from "lucide-react";
import Link from "@/components/native-link";
import { FindingsFilterForm } from "@/components/findings/filter-form";
import { FindingsResults } from "@/components/findings/findings-results";
import { InstitutionPicker } from "@/components/findings/institution-picker";
import { TypesPopover } from "@/components/findings/types-popover";
import {
  FILTER_PLATFORM_OPTIONS, FILTER_SELECT_CLASS, FINDINGS_DIRECTION_CLASS, FINDINGS_FILTERS_CLASS, FINDINGS_INSTITUTION_CLASS,
  FINDINGS_MODE_CLASS, FINDINGS_PERIOD_CLASS, FINDINGS_PLATFORM_CLASS, FINDINGS_SEARCH_CLASS, FINDINGS_SORT_CLASS, FINDINGS_TOOLBAR_CLASS,
} from "@/components/filter-toolbar";
import { MethodNote } from "@/components/method-note";
import { NativeSegments } from "@/components/native-field";
import { SortDirection } from "@/components/sort-direction";
import { NavigationBoundary } from "@/components/navigation-boundary";
import { StatisticsSkeleton } from "@/components/skeletons";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Empty, EmptyContent, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { anomalyReportVisible } from "@/lib/anomaly-visibility";
import { api, ApiError } from "@/lib/api";
import { DEFAULT_FINDINGS_QUERY, FINDINGS_PERIOD_OPTIONS, FINDINGS_SORT_OPTIONS, findingsHrefQuery, normalizeFindingsQuery } from "@/lib/findings";
import { formatDate } from "@/lib/format";
import { first, queryHref, type SearchParams } from "@/lib/params";
import type { FindingInstitution, FindingsPage, FindingsRequest } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Находки: посты выше нормы",
  description: "Посты вузов, сработавшие лучше обычного для своего аккаунта: индекс к норме на одном возрасте поста.",
};

const MODE_OPTIONS = [
  { value: "all", label: "Все вузы", title: "Лучшие посты всех вузов" },
  { value: "institution", label: "Мой вуз", title: "Посты одного вуза" },
] as const;

export default async function FindingsPageRoute({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const raw = await searchParams;
  const query = normalizeFindingsQuery(raw);
  // «Мой вуз» без выбранного вуза — пустое состояние с выбором, без запроса постов.
  const choosing = first(raw.mode) === "institution" && query.mode === "all";
  const anomaliesVisible = anomalyReportVisible();
  const anomalies: FindingsRequest["anomalies"] = anomaliesVisible ? "exclude" : "include";
  const cursor = first(raw.cursor);
  let page: FindingsPage | null = null;
  let institutions: FindingInstitution[] = [];
  let failed = false;
  let staleCursor = false;
  let unknownInstitution = false;
  // Список вузов приходит с любой выдачей. Без выбранного вуза берём его из
  // выдачи по умолчанию («Все вузы», 7 дней, 50 постов): её греет прогрев
  // кэша, поэтому выбор вуза не запускает отдельный тяжёлый запрос.
  const defaultListing = { ...DEFAULT_FINDINGS_QUERY, anomalies, limit: 50 };
  try {
    page = await api.findings(choosing ? defaultListing : { ...query, anomalies, limit: 50, cursor });
    institutions = page.institutions;
  } catch (error) {
    // Курсор при выборе вуза не отправляется: 400 тогда — обычная ошибка.
    if (error instanceof ApiError && error.status === 400 && cursor && !choosing) staleCursor = true;
    else if (error instanceof ApiError && error.status === 404 && query.mode === "institution") {
      unknownInstitution = true;
      institutions = await api.findings(defaultListing).then((body) => body.institutions, () => []);
    } else failed = true;
  }
  // Курсор устарел (сменилась ревизия): начинаем список заново. redirect()
  // бросает собственное исключение, поэтому вызывается вне try.
  if (staleCursor) redirect(queryHref("/statistics", findingsHrefQuery(query)));

  const institutionMode = query.mode === "institution" || choosing || unknownInstitution;
  // «Мой вуз» без вуза нормализуется в тот же запрос, что и «Все вузы»: режим
  // входит в ключ, иначе форма не пересоздаётся и хранит прежние поля.
  const selectionKey = JSON.stringify([findingsHrefQuery(query), institutionMode]);
  const updated = page ? new Date(page.asOf).toLocaleTimeString("ru-RU", { timeZone: "Europe/Moscow", hour: "2-digit", minute: "2-digit" }) : null;

  return <>
    <PageHeader
      title="Находки: посты выше нормы"
      titleNote={<MethodNote title="Как считается индекс"><p>Индекс — взаимодействия поста на 24-м часу (у свежих — на последнем замере), делённые на типичное значение его аккаунта на том же часу за 30 дней.</p>{anomaliesVisible ? <p>Посты с выраженной аномалией не входят ни в норму, ни в выдачу.</p> : null}<p><Link href="/methodology/findings" prefetch={false} className="underline underline-offset-4">Подробнее о методике</Link></p></MethodNote>}
      description="Посты, которые сработали лучше обычного для своего аккаунта."
      meta={page ? <span className="text-muted-foreground text-xs" title={`${formatDate(page.asOf)} · datasetRevision ${page.datasetRevision}`}>Обновлено {updated}</span> : null}
    />
    {!anomaliesVisible ? <Alert className="mb-4"><AlertDescription>Проверка аномалий временно недоступна — посты не отфильтрованы.</AlertDescription></Alert> : null}

    <FindingsFilterForm key={selectionKey} id="findings-filters" action="/statistics" method="get" aria-label="Фильтры находок"
      data-testid="filter-toolbar" className={FINDINGS_TOOLBAR_CLASS}>
      <div className={FINDINGS_MODE_CLASS}><NativeSegments name="mode" legend="Режим" value={institutionMode ? "institution" : "all"}
        options={MODE_OPTIONS} labelled={false} stretch /></div>
      {query.mode === "institution" && !unknownInstitution
        ? <div className={FINDINGS_INSTITUTION_CLASS}><InstitutionPicker institutions={institutions} value={query.institution} /></div> : null}
      <div className={FINDINGS_PLATFORM_CLASS}><NativeSegments name="platform" legend="Площадка" value={query.platform}
        options={FILTER_PLATFORM_OPTIONS} labelled={false} stretch /></div>
      <div className={FINDINGS_PERIOD_CLASS}><NativeSegments name="period" legend="Период" value={query.period}
        options={FINDINGS_PERIOD_OPTIONS} labelled={false} stretch /></div>
      <div className={FINDINGS_DIRECTION_CLASS}><SortDirection name="direction" value={query.direction} legend="Направление сортировки" /></div>
      <div className={FINDINGS_SORT_CLASS}>
        <NativeSelect name="sort" defaultValue={query.sort} aria-label="Сортировка" className={FILTER_SELECT_CLASS}>
          {FINDINGS_SORT_OPTIONS.map(([value, label]) => <NativeSelectOption key={value} value={value}>{label}</NativeSelectOption>)}
        </NativeSelect>
      </div>
      <div className={FINDINGS_FILTERS_CLASS}><TypesPopover value={query.types} group={query.group} groupAvailable={!institutionMode} /></div>
      <div className={FINDINGS_SEARCH_CLASS}>
        <InputGroup className="h-8">
          <InputGroupAddon><Search className="size-4" aria-hidden="true" /></InputGroupAddon>
          <InputGroupInput name="q" type="search" defaultValue={query.q} maxLength={200} placeholder="Номер, URL или аккаунт" aria-label="Поиск публикаций" className="text-sm md:text-sm" />
          <InputGroupAddon align="inline-end">
            {query.q ? <InputGroupButton size="icon-sm" className="size-6" nativeButton={false} aria-label="Очистить поиск" title="Очистить поиск"
              render={<Link role="link" href={queryHref("/statistics", { ...findingsHrefQuery(query), q: undefined })} prefetch={false} />}><X className="size-3.5" aria-hidden="true" /></InputGroupButton> : null}
            <InputGroupButton type="submit" variant="secondary" size="icon-sm" className="size-6" aria-label="Применить фильтры" title="Применить фильтры"><ArrowRight className="size-3.5" aria-hidden="true" /></InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
      </div>
    </FindingsFilterForm>

    <NavigationBoundary fallback={<StatisticsSkeleton chrome={false} />}>
      {failed ? <ApiFailureState retryHref={queryHref("/statistics", findingsHrefQuery(query))} />
        : choosing || unknownInstitution || !page ? <Empty key={selectionKey} role="status" className="bg-card border py-10">
            <EmptyHeader><EmptyTitle><h2 className="font-heading text-lg font-semibold">{unknownInstitution ? "Вуз не найден — выберите другой" : "Выберите вуз, чтобы увидеть его посты"}</h2></EmptyTitle></EmptyHeader>
            {choosing || unknownInstitution ? <EmptyContent className="w-full max-w-64">
              <InstitutionPicker institutions={institutions} value={query.institution} form="findings-filters" />
            </EmptyContent> : null}
          </Empty>
        : <FindingsResults key={selectionKey} page={page} query={query} anomaliesVisible={anomaliesVisible} />}
    </NavigationBoundary>
  </>;
}
