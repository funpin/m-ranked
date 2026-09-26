import type { Metadata } from "next";
import Link from "@/components/native-link";
import { ArticleToc } from "@/components/methodology/article-toc";
import { CopyButton } from "@/components/methodology/copy-button";
import { API_DIGEST, PARAMETER_TEXT, operationAnchor, operationsBySection, type ApiParameter } from "@/lib/api-reference";
import { publicOrigin } from "@/lib/deployment";
import type { TocEntry } from "@/lib/methodology";
import { REPOSITORY_URL } from "@/lib/repository";

const DESCRIPTION = "Публичные методы API m-ranked с параметрами и примерами запросов: рейтинг, сравнение, аккаунты, публикации и история замеров.";
export const metadata: Metadata = {
  title: "Открытый API — методология",
  description: DESCRIPTION,
  alternates: { canonical: "/methodology/api" },
  openGraph: { title: "Открытый API m-ranked", description: DESCRIPTION },
};

const CONTRACT_URL = `${REPOSITORY_URL}/blob/main/contracts/openapi/m-ranked-v1.yaml`;

function constraint(parameter: ApiParameter) {
  if (parameter.enum) return parameter.enum.join(" · ");
  if (parameter.minimum !== undefined && parameter.maximum !== undefined) return `${parameter.minimum}–${parameter.maximum}`;
  if (parameter.minimum !== undefined) return `от ${parameter.minimum}`;
  return null;
}

/** Справочник открытого API. Методы и параметры берутся из контракта OpenAPI
 *  при сборке, поэтому страница не расходится с тем, что API отвечает. */
export default function ApiReferencePage() {
  const origin = publicOrigin().origin;
  const sections = operationsBySection();
  const toc: TocEntry[] = sections.flatMap((section) => [
    { id: `section-${section.id}`, text: section.title, level: 2 as const },
    ...section.operations.map((operation) => ({ id: operationAnchor(operation.operationId), text: operation.title, level: 3 as const })),
  ]);
  return (
    <div className="grid gap-12 xl:grid-cols-[minmax(0,1fr)_208px]">
      <article data-article className="max-w-[80ch] min-w-0" data-testid="api-reference">
        <header className="mb-10 grid gap-4 border-b pb-8">
          <p className="text-muted-foreground font-mono text-xs">Методология / API · версия {API_DIGEST.version}</p>
          <h1 className="font-heading text-4xl leading-[1.05] font-bold tracking-tight sm:text-5xl">Открытый API</h1>
          <p className="text-muted-foreground text-lg leading-relaxed text-pretty">
            Те же данные, что на сайте, в JSON. Ключ не нужен. Здесь — публичные методы чтения; полный контракт — в
            {" "}<a href={CONTRACT_URL} target="_blank" rel="noopener noreferrer" className="text-foreground underline underline-offset-4">OpenAPI 3.1</a>.
          </p>
        </header>

        <section aria-labelledby="basics" className="mb-14 grid gap-4">
          <h2 id="basics" className="font-heading text-2xl font-bold tracking-tight">Как обращаться</h2>
          <ul className="text-foreground/90 ml-5 list-disc space-y-2 text-base leading-relaxed">
            <li>Адрес: <code className="bg-muted rounded-md px-1.5 py-0.5 font-mono text-[0.85em]">{origin}/api/v1/…</code>, только GET.</li>
            <li>Каждый ответ несёт <code className="bg-muted rounded-md px-1.5 py-0.5 font-mono text-[0.85em]">datasetRevision</code> и
              {" "}<code className="bg-muted rounded-md px-1.5 py-0.5 font-mono text-[0.85em]">asOf</code> — ревизию данных и момент расчёта.</li>
            <li>Ответы кэшируются: повторите запрос с <code className="bg-muted rounded-md px-1.5 py-0.5 font-mono text-[0.85em]">If-None-Match</code> и
              полученным <code className="bg-muted rounded-md px-1.5 py-0.5 font-mono text-[0.85em]">ETag</code> — если данные не изменились, придёт 304 без тела.</li>
            <li>Отсутствующее значение — <code className="bg-muted rounded-md px-1.5 py-0.5 font-mono text-[0.85em]">null</code>, а не 0
              (<Link href="/methodology/platforms" prefetch={false} className="underline underline-offset-4">почему</Link>).</li>
            <li>Будьте бережны: частые запросы с одного адреса получают 429 или 503 с заголовком Retry-After.</li>
          </ul>
        </section>

        {sections.map((section) => (
          <section key={section.id} aria-labelledby={`section-${section.id}`} className="mb-14 grid gap-6">
            <h2 id={`section-${section.id}`} className="font-heading scroll-mt-24 text-2xl font-bold tracking-tight sm:text-3xl">{section.title}</h2>
            {section.operations.map((operation) => {
              const anchor = operationAnchor(operation.operationId);
              const command = `curl -s "${origin}${operation.example ?? operation.path}"`;
              return (
                <div key={operation.operationId} className="bg-card ring-foreground/10 grid gap-4 rounded-2xl p-5 ring-1 sm:p-6" data-operation={operation.operationId}>
                  <div className="grid gap-2">
                    <h3 id={anchor} className="font-heading scroll-mt-24 text-xl font-semibold tracking-tight">{operation.title}</h3>
                    <p className="flex flex-wrap items-center gap-2 font-mono text-sm">
                      <span className="bg-chart-1/15 text-foreground rounded-md px-1.5 py-0.5 text-xs font-semibold">GET</span>
                      <span className="break-all">{operation.path}</span>
                    </p>
                    <p className="text-muted-foreground text-sm leading-relaxed">{operation.text}</p>
                  </div>
                  {operation.parameters.length > 0 && (
                    <div className="ring-foreground/10 focus-visible:ring-ring/60 overflow-x-auto rounded-xl ring-1 outline-none focus-visible:ring-2" tabIndex={0} role="region" aria-label={`Параметры: ${operation.title}`}>
                      <table className="w-full border-collapse text-sm">
                        <caption className="sr-only">Параметры: {operation.title}</caption>
                        <thead className="bg-muted/50">
                          <tr>
                            {["Параметр", "Тип", "Значения", "Описание"].map((label) => (
                              <th key={label} scope="col" className="text-muted-foreground px-3 py-2 text-left text-xs font-medium tracking-wide uppercase">{label}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {operation.parameters.map((parameter) => (
                            <tr key={`${parameter.in}-${parameter.name}`}>
                              <td className="border-t px-3 py-2 align-top font-mono text-xs whitespace-nowrap">
                                {parameter.name}{parameter.in === "path" && <span className="text-muted-foreground"> · путь</span>}
                                {parameter.required && <span className="text-destructive" title="обязательный"> *</span>}
                              </td>
                              <td className="text-muted-foreground border-t px-3 py-2 align-top font-mono text-xs">{parameter.type}</td>
                              <td className="border-t px-3 py-2 align-top font-mono text-xs">
                                {constraint(parameter)}
                                {parameter.default !== undefined && <span className="text-muted-foreground block">по умолчанию {String(parameter.default)}</span>}
                              </td>
                              <td className="text-muted-foreground border-t px-3 py-2 align-top text-xs">{PARAMETER_TEXT[parameter.name] ?? ""}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <div className="bg-muted/60 ring-foreground/10 flex items-center gap-2 rounded-xl py-1.5 pr-1.5 pl-4 ring-1">
                    <code className="focus-visible:ring-ring/60 min-w-0 flex-1 overflow-x-auto rounded py-1 font-mono text-[13px] whitespace-nowrap outline-none focus-visible:ring-2" tabIndex={0}>{command}</code>
                    <CopyButton text={command} />
                  </div>
                  {operation.response && (
                    <details className="group text-sm">
                      <summary className="text-muted-foreground hover:text-foreground cursor-pointer">
                        Ответ: <span className="font-mono">{operation.response}</span> · {operation.fields.length} полей
                      </summary>
                      <ul className="mt-3 flex flex-wrap gap-1.5">
                        {operation.fields.map((field) => (
                          <li key={field.name} className="bg-muted/60 rounded-md px-2 py-1 font-mono text-xs">
                            {field.name}<span className="text-muted-foreground">: {field.type}</span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              );
            })}
          </section>
        ))}
        <p className="text-muted-foreground border-t pt-6 text-sm">
          Справочник собирается из контракта при сборке сайта. Идентификаторы в примерах вида {"{uuid}"} замените на
          настоящие — они есть в адресах страниц аккаунтов и публикаций.
        </p>
      </article>
      <aside className="max-xl:hidden">
        <div className="sticky top-20 max-h-[calc(100svh-6rem)] overflow-y-auto"><ArticleToc entries={toc} /></div>
      </aside>
    </div>
  );
}
