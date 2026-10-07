import Link from "@/components/native-link";
import { cn } from "@/lib/utils";

/** Переключатель периода ссылками: страница перерисовывается на сервере,
 *  без клиентского состояния и повторных запросов из браузера. */
export function RangeSwitch<T extends string>({ value, options, href, label }: {
  value: T; options: readonly (readonly [T, string])[]; href: (value: T) => string; label: string;
}) {
  return (
    <nav aria-label={label} className="bg-muted inline-flex rounded-lg p-[3px]">
      {options.map(([option, text]) => (
        <Link key={option} href={href(option)} prefetch={false} aria-current={option === value ? "page" : undefined}
          className={cn("rounded-md px-3 py-1 text-xs font-medium no-underline transition-colors",
            option === value ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
          {text}
        </Link>
      ))}
    </nav>
  );
}
