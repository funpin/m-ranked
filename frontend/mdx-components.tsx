import type { MDXComponents } from "mdx/types";
import { Children, isValidElement, type ReactNode } from "react";
import Link from "@/components/native-link";
import { slugify } from "@/lib/methodology";
import { cn } from "@/lib/utils";

/** Текст узла без разметки — для якоря заголовка. */
function textOf(node: ReactNode): string {
  return Children.toArray(node).map((child) => {
    if (typeof child === "string" || typeof child === "number") return String(child);
    if (isValidElement<{ children?: ReactNode }>(child)) return textOf(child.props.children);
    return "";
  }).join("");
}

function Heading({ level, children }: { level: 2 | 3; children?: ReactNode }) {
  const id = slugify(textOf(children));
  const Tag = level === 2 ? "h2" : "h3";
  return (
    <Tag id={id} className={cn("group font-heading scroll-mt-24 tracking-tight text-balance",
      level === 2 ? "mt-14 mb-4 text-2xl font-bold sm:text-3xl" : "mt-10 mb-3 text-xl font-semibold")}>
      {children}
      <a href={`#${id}`} aria-label="Ссылка на раздел"
        className="text-muted-foreground/50 hover:text-foreground ml-2 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100">#</a>
    </Tag>
  );
}

/** Оформление статей методологии в стиле интерфейса: те же шрифты, цвета и
 *  радиусы, что у остального сайта. Внутренние ссылки — без предзагрузки. */
const components: MDXComponents = {
  h2: ({ children }) => <Heading level={2}>{children}</Heading>,
  h3: ({ children }) => <Heading level={3}>{children}</Heading>,
  p: ({ children }) => <p className="text-foreground/90 my-5 text-base leading-[1.75]">{children}</p>,
  a: ({ href = "", children }) => href.startsWith("/")
    ? <Link href={href} prefetch={false} className="text-foreground decoration-chart-2/60 hover:decoration-chart-2 font-medium underline underline-offset-4 transition-colors">{children}</Link>
    : <a href={href} target={href.startsWith("#") ? undefined : "_blank"} rel={href.startsWith("#") ? undefined : "noopener noreferrer"}
      className="text-foreground decoration-chart-2/60 hover:decoration-chart-2 font-medium underline underline-offset-4 transition-colors">{children}</a>,
  ul: ({ children }) => <ul className="text-foreground/90 my-5 ml-5 list-disc space-y-2 text-base leading-[1.7] marker:text-muted-foreground">{children}</ul>,
  ol: ({ children }) => <ol className="text-foreground/90 my-5 ml-5 list-decimal space-y-2 text-base leading-[1.7] marker:text-muted-foreground">{children}</ol>,
  li: ({ children }) => <li className="pl-1">{children}</li>,
  strong: ({ children }) => <strong className="text-foreground font-semibold">{children}</strong>,
  blockquote: ({ children }) => (
    <blockquote className="bg-muted/40 border-chart-2 my-6 rounded-r-xl border-l-2 px-5 py-1 [&>p]:my-3">{children}</blockquote>
  ),
  code: ({ children }) => <code className="bg-muted rounded-md px-1.5 py-0.5 font-mono text-[0.85em]">{children}</code>,
  pre: ({ children }) => (
    <pre tabIndex={0} className="bg-muted/60 ring-foreground/10 focus-visible:ring-ring/60 outline-none focus-visible:ring-2 my-6 overflow-x-auto rounded-xl p-4 font-mono text-[13px] leading-6 ring-1 [&_code]:bg-transparent [&_code]:p-0">{children}</pre>
  ),
  table: ({ children }) => (
    // Широкая таблица прокручивается вбок: область доступна и с клавиатуры.
    <div className="ring-foreground/10 focus-visible:ring-ring/60 my-6 overflow-x-auto rounded-xl ring-1 outline-none focus-visible:ring-2"
      tabIndex={0} role="region" aria-label="Таблица">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
  th: ({ children }) => <th className="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium tracking-wide uppercase">{children}</th>,
  td: ({ children }) => <td className="border-t px-4 py-2.5 align-top tabular-nums">{children}</td>,
  hr: () => <hr className="my-10" />,
};

export function useMDXComponents(): MDXComponents {
  return components;
}
