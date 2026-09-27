import type { Metadata } from "next";
import { ArrowRight, Braces, Eye, Scale, ShieldQuestion } from "lucide-react";
import Link from "@/components/native-link";
import { GithubMark } from "@/components/github-mark";
import { ARTICLES } from "@/lib/methodology";
import { REPOSITORY_URL } from "@/lib/repository";

const DESCRIPTION = "Как m-ranked собирает публичные счётчики соцсетей вузов, проверяет их, сравнивает вузы и анализирует динамику публикаций.";
export const metadata: Metadata = {
  title: "Методология",
  description: DESCRIPTION,
  alternates: { canonical: "/methodology" },
  openGraph: { title: "Методология m-ranked", description: DESCRIPTION },
};

const PRINCIPLES = [
  { icon: Eye, title: "Только публичное", text: "Берём счётчики, которые видит любой читатель. Закрытых данных площадок у нас нет." },
  { icon: Scale, title: "Честное сравнение", text: "Сравниваем посты одного возраста и не складываем несопоставимые показатели." },
  { icon: ShieldQuestion, title: "Наблюдение, а не обвинение", text: "Анализ называет форму отклонения и её силу, рядом — объяснения, которые данные не исключают." },
] as const;

export default function MethodologyIndex() {
  return (
    <div className="grid gap-14 pb-10">
      <header className="grid max-w-3xl gap-5">
        <p className="text-muted-foreground text-xs font-medium tracking-[0.14em] uppercase">Документация</p>
        <h1 className="font-heading text-5xl leading-[1] font-bold tracking-tight sm:text-6xl">Методология</h1>
        <p className="text-muted-foreground text-lg leading-relaxed text-pretty">
          Как устроен m-ranked: что и как часто мы замеряем, какие значения считаем достоверными, как сравниваем вузы и
          что именно сообщает анализ динамики. Каждая статья ссылается на код, который можно прочитать.
        </p>
      </header>

      <ul className="grid gap-3 sm:grid-cols-3">
        {PRINCIPLES.map(({ icon: Icon, title, text }) => (
          <li key={title} className="bg-muted/40 ring-foreground/5 grid gap-2 rounded-2xl p-5 ring-1">
            <Icon className="text-chart-2 size-5" aria-hidden="true" />
            <p className="font-heading font-bold tracking-tight">{title}</p>
            <p className="text-muted-foreground text-sm leading-relaxed">{text}</p>
          </li>
        ))}
      </ul>

      <section aria-labelledby="articles" className="grid gap-5">
        <h2 id="articles" className="font-heading text-2xl font-bold tracking-tight">Статьи по порядку</h2>
        <ol className="grid gap-3 md:grid-cols-2" data-testid="methodology-articles">
          {ARTICLES.map((article, index) => (
            <li key={article.slug}>
              <Link href={`/methodology/${article.slug}`} prefetch={false}
                className="group bg-card ring-foreground/10 hover:ring-foreground/25 focus-visible:ring-ring/60 flex h-full gap-4 rounded-2xl p-5 ring-1 transition-[box-shadow,transform] outline-none hover:-translate-y-0.5 focus-visible:ring-2 motion-reduce:hover:translate-y-0">
                <span className="text-muted-foreground font-mono text-sm tabular-nums">{String(index + 1).padStart(2, "0")}</span>
                <span className="grid flex-1 gap-1">
                  <span className="font-heading text-lg font-bold tracking-tight">{article.title}</span>
                  <span className="text-muted-foreground text-sm leading-relaxed">{article.description}</span>
                </span>
                <ArrowRight className="text-muted-foreground size-4 shrink-0 self-center transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="data" className="grid gap-3 sm:grid-cols-2">
        <h2 id="data" className="sr-only">Данные и код</h2>
        <Link href="/methodology/api" prefetch={false}
          className="group bg-card ring-foreground/10 hover:ring-foreground/25 grid gap-2 rounded-2xl p-5 ring-1 transition-shadow">
          <Braces className="text-chart-2 size-5" aria-hidden="true" />
          <span className="font-heading text-lg font-bold tracking-tight">Открытый API</span>
          <span className="text-muted-foreground text-sm">Публичные методы с примерами запросов: те же данные, что на сайте.</span>
        </Link>
        <a href={REPOSITORY_URL} target="_blank" rel="noopener noreferrer"
          className="group bg-card ring-foreground/10 hover:ring-foreground/25 grid gap-2 rounded-2xl p-5 ring-1 transition-shadow">
          <GithubMark className="size-5" />
          <span className="font-heading text-lg font-bold tracking-tight">Исходный код</span>
          <span className="text-muted-foreground text-sm">Сборщики, база, анализ и сайт — в одном открытом репозитории.</span>
        </a>
      </section>
    </div>
  );
}
