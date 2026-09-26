import { readFile } from "node:fs/promises";
import path from "node:path";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ArrowLeft, ArrowRight, PencilLine } from "lucide-react";
import Link from "@/components/native-link";
import { ArticleToc } from "@/components/methodology/article-toc";
import { ARTICLES, articleBySlug, editUrl, headingsOf, neighbours } from "@/lib/methodology";

export const dynamicParams = false;

export function generateStaticParams() {
  return ARTICLES.map((article) => ({ slug: article.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const article = articleBySlug((await params).slug);
  if (!article) return {};
  return {
    title: `${article.title} — методология`,
    description: article.description,
    alternates: { canonical: `/methodology/${article.slug}` },
    openGraph: { title: `${article.title} — методология m-ranked`, description: article.description },
  };
}

export default async function ArticlePage({ params }: { params: Promise<{ slug: string }> }) {
  const article = articleBySlug((await params).slug);
  if (!article) notFound();
  const [{ default: Content }, source] = await Promise.all([
    import(`@/content/methodology/${article.slug}.mdx`),
    readFile(path.join(process.cwd(), "content/methodology", `${article.slug}.mdx`), "utf8"),
  ]);
  const { previous, next } = neighbours(article.slug);
  const number = ARTICLES.findIndex((item) => item.slug === article.slug) + 1;
  return (
    <div className="grid gap-12 xl:grid-cols-[minmax(0,1fr)_208px]">
      <article data-article className="max-w-[72ch] min-w-0">
        <header className="mb-10 grid gap-4 border-b pb-8">
          <p className="text-muted-foreground font-mono text-xs">
            <Link href="/methodology" prefetch={false} className="hover:text-foreground transition-colors">Методология</Link>
            <span aria-hidden="true"> / </span>{String(number).padStart(2, "0")}
          </p>
          <h1 className="font-heading text-4xl leading-[1.05] font-bold tracking-tight text-balance sm:text-5xl">{article.title}</h1>
          <p className="text-muted-foreground text-lg leading-relaxed text-pretty">{article.description}</p>
        </header>
        <Content />
        <footer className="mt-16 grid gap-6 border-t pt-8">
          <a href={editUrl(article.slug)} target="_blank" rel="noopener noreferrer"
            className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-2 text-sm transition-colors">
            <PencilLine className="size-4" aria-hidden="true" />Нашли неточность? Исправьте статью на GitHub
          </a>
          <nav aria-label="Соседние статьи" className="grid gap-3 sm:grid-cols-2">
            {previous ? (
              <Link href={`/methodology/${previous.slug}`} prefetch={false}
                className="group bg-card ring-foreground/10 hover:ring-foreground/25 grid gap-1 rounded-2xl p-4 ring-1 transition-shadow">
                <span className="text-muted-foreground inline-flex items-center gap-1 text-xs"><ArrowLeft className="size-3.5 transition-transform group-hover:-translate-x-0.5" aria-hidden="true" />Назад</span>
                <span className="font-medium">{previous.title}</span>
              </Link>
            ) : <span />}
            {next && (
              <Link href={`/methodology/${next.slug}`} prefetch={false}
                className="group bg-card ring-foreground/10 hover:ring-foreground/25 grid gap-1 rounded-2xl p-4 text-right ring-1 transition-shadow">
                <span className="text-muted-foreground inline-flex items-center justify-end gap-1 text-xs">Дальше<ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" /></span>
                <span className="font-medium">{next.title}</span>
              </Link>
            )}
          </nav>
        </footer>
      </article>
      <aside className="max-xl:hidden">
        <div className="sticky top-20"><ArticleToc entries={headingsOf(source)} /></div>
      </aside>
    </div>
  );
}
