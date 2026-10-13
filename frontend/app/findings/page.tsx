import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { ArrowRight, Search, X } from "lucide-react";
import Link from "@/components/native-link";
import { AnomalousResults } from "@/components/findings/anomalous-results";
import { CleanToggle } from "@/components/findings/clean-toggle";
import { FindingsFilterForm } from "@/components/findings/filter-form";
import { FindingsResults } from "@/components/findings/findings-results";
import { FindingsViewTabs } from "@/components/findings/view-tabs";
import { InstitutionPicker } from "@/components/findings/institution-picker";
import { TypesPopover } from "@/components/findings/types-popover";
import { FILTER_PLATFORM_OPTIONS, FILTER_SELECT_CLASS } from "@/components/filter-toolbar";
import {
  FINDINGS_DIRECTION_CLASS, FINDINGS_FILTERS_CLASS, FINDINGS_INSTITUTION_CLASS, FINDINGS_MODE_CLASS, FINDINGS_PERIOD_CLASS, FINDINGS_PLATFORM_CLASS, FINDINGS_SEARCH_CLASS, FINDINGS_SORT_CLASS, FINDINGS_TOOLBAR_CLASS,
} from "@/components/findings/toolbar";
import { MethodNote } from "@/components/method-note";
import { NativeSegments } from "@/components/native-field";
import { SortDirection } from "@/components/sort-direction";
import { NavigationBoundary } from "@/components/navigation-boundary";
import { FindingsSkeleton } from "@/components/skeletons";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Empty, EmptyContent, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { anomalyReportVisible } from "@/lib/anomaly-visibility";
import { api, ApiError } from "@/lib/api";
import { DEFAULT_FINDINGS_QUERY, FINDINGS_PERIOD_OPTIONS, findingsHrefQuery, normalizeFindingsQuery, periodRange, sortOptionsFor } from "@/lib/findings";
import { formatDate } from "@/lib/format";
import { first, queryHref, type SearchParams } from "@/lib/params";
import type { AnomalousFindingsPage, FindingInstitution, FindingsPage, FindingsRequest } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Находки",
  description: "Посты вузов, сработавшие лучше обычного для своего аккаунта, и посты с самой необычной динамикой счётчиков.",
};

const MODE_OPTIONS = [
  { value: "all", label: "Все вузы", title: "Лучшие посты всех вузов" },
  { value: "institution", label: "Мой вуз", title: "Посты одного вуза" },
] as const;

export default async function FindingsPageRoute({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const raw = await searchParams;
  const parsed = normalizeFindingsQuery(raw);
  const anomaliesVisible = anomalyReportVisible();
  // Без отчёта об аномалиях раздела «Аномальные посты» и пометок находок нет.
  const query = anomaliesVisible ? parsed : { ...parsed, view: "above_norm" as const, clean: false,
    sort: parsed.view === "anomalous" ? "interaction_index" as const : parsed.sort };
  const anomalous = query.view === "anomalous";
  // «Мой вуз» без выбранного вуза — пустое состояние с выбором, без запроса постов.
  const choosing = first(raw.mode) === "institution" && query.mode === "all";
  const anomalies: FindingsRequest["anomalies"] = anomaliesVisible ? "exclude" : "include";
  const cursor = first(raw.cursor);
  let page: FindingsPage | AnomalousFindingsPage | null = null;
  let institutions: FindingInstitution[] = [];
  let failed = false;
  let staleCursor = false;
  let unknownInstitution = false;
  // Список вузов приходит с любой выдачей. Без выбранного вуза берём его из
  // выдачи по умолчанию («Все вузы», 7 дней, 50 постов): её греет прогрев
  // кэша, поэтому выбор вуза не запускает отдельный тяжёлый запрос.
  const defaultListing = { ...DEFAULT_FINDINGS_QUERY, anomalies, limit: 50 };
  try {
    page = choosing ? await api.findings(defaultListing)
      : anomalous ? await api.anomalousFindings({ ...query, anomalies, limit: 50, cursor })
        : await api.findings({ ...query, anomalies, limit: 50, cursor });
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
  if (staleCursor) redirect(queryHref("/findings", findingsHrefQuery(query)));

  const institutionMode = query.mode === "institution" || choosing || unknownInstitution;
  // «Мой вуз» без вуза нормализуется в тот же запрос, что и «Все вузы»: режим
  // входит в ключ, иначе форма не пересоздаётся и хранит прежние поля.
  const selectionKey = JSON.stringify([findingsHrefQuery(query), institutionMode]);
  const updated = page ? new Date(page.asOf).toLocaleTimeString("ru-RU", { timeZone: "Europe/Moscow", hour: "2-digit", minute: "2-digit" }) : null;

  return <>
    <PageHeader
      title="Находки"
      titleNote={anomalous
        ? <MethodNote title="Как строится рейтинг"><p>В рейтинг входят посты периода с уровнем «выраженная аномалия» и выше. Порядок — уровень, затем доля необычного прироста: какая часть итогового значения метрики набрана в участке признака.</p><p>Это необычность счётчиков, а не доказательство накрутки: у каждого признака на странице поста названы честные объяснения.</p><p><Link href="/methodology/findings" prefetch={false} className="underline underline-offset-4">Подробнее о методике</Link></p></MethodNote>
        : <MethodNote title="Как считается индекс"><p>Индекс — взаимодействия поста на 24-м часу (у свежих — на последнем замере), делённые на типичное значение его аккаунта на том же часу за 30 дней.</p>{anomaliesVisible ? <p>Посты с выраженной аномалией не входят ни в норму, ни в выдачу.</p> : null}<p><Link href="/methodology/findings" prefetch={false} className="underline underline-offset-4">Подробнее о методике</Link></p></MethodNote>}
      description={anomalous ? "Посты с самой необычной динамикой счётчиков: сильнейшие признаки первыми."
        : "Посты, которые сработали лучше обычного для своего аккаунта."}
      meta={page ? <span className="text-muted-foreground text-xs" title={`${formatDate(page.asOf)} · datasetRevision ${page.datasetRevision}`}>
        Обновлено {updated}<span className="block sm:inline"><span className="hidden sm:inline"> · </span>период {periodRange(page.asOf, query.period)}</span>
      </span> : null}
    />
    {!anomaliesVisible ? <Alert className="mb-4"><AlertDescription>Проверка аномалий временно недоступна — посты не отфильтрованы.</AlertDescription></Alert> : null}
    {anomaliesVisible ? <FindingsViewTabs query={query} /> : null}

    <FindingsFilterForm key={selectionKey} id="findings-filters" action="/findings" method="get" aria-label="Фильтры находок"
      data-testid="filter-toolbar" className={FINDINGS_TOOLBAR_CLASS}>
      {anomalous ? <input type="hidden" name="view" value="anomalous" /> : null}
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
          {sortOptionsFor(query.platform, query.view).map(([value, label]) => <NativeSelectOption key={value} value={value}>{label}</NativeSelectOption>)}
        </NativeSelect>
      </div>
      <div className={FINDINGS_FILTERS_CLASS}><TypesPopover value={query.types} group={query.group} groupAvailable={!institutionMode} /></div>
      <div className={FINDINGS_SEARCH_CLASS}>
        <InputGroup className="h-8">
          <InputGroupAddon><Search className="size-4" aria-hidden="true" /></InputGroupAddon>
          <InputGroupInput name="q" type="search" defaultValue={query.q} maxLength={200} placeholder="Номер, URL или аккаунт" aria-label="Поиск публикаций" className="text-sm md:text-sm" />
          <InputGroupAddon align="inline-end">
            {query.q ? <InputGroupButton size="icon-sm" className="size-6" nativeButton={false} aria-label="Очистить поиск" title="Очистить поиск"
              render={<Link role="link" href={queryHref("/findings", { ...findingsHrefQuery(query), q: undefined })} prefetch={false} />}><X className="size-3.5" aria-hidden="true" /></InputGroupButton> : null}
            <InputGroupButton type="submit" variant="secondary" size="icon-sm" className="size-6" aria-label="Применить фильтры" title="Применить фильтры"><ArrowRight className="size-3.5" aria-hidden="true" /></InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
      </div>
    </FindingsFilterForm>
    {anomaliesVisible && page && !choosing && (page.hiddenByFindings > 0 || query.clean)
      ? <CleanToggle key={String(query.clean)} form="findings-filters" clean={query.clean} count={page.hiddenByFindings} /> : null}

    <NavigationBoundary fallback={<FindingsSkeleton chrome={false} />}>
      {failed ? <ApiFailureState retryHref={queryHref("/findings", findingsHrefQuery(query))} />
        : choosing || unknownInstitution || !page ? <Empty key={selectionKey} role="status" className="bg-card border py-10">
            <EmptyHeader><EmptyTitle><h2 className="font-heading text-lg font-semibold">{unknownInstitution ? "Вуз не найден — выберите другой" : "Выберите вуз, чтобы увидеть его посты"}</h2></EmptyTitle></EmptyHeader>
            {choosing || unknownInstitution ? <EmptyContent className="w-full max-w-64">
              <InstitutionPicker institutions={institutions} value={query.institution} form="findings-filters" />
            </EmptyContent> : null}
          </Empty>
        : anomalous ? <AnomalousResults key={selectionKey} page={page as AnomalousFindingsPage} query={query} />
          : <FindingsResults key={selectionKey} page={page as FindingsPage} query={query} anomaliesVisible={anomaliesVisible} />}
    </NavigationBoundary>
  </>;
}
