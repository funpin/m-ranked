
import Link from "@/components/native-link";

export default function NotFound() {
  return (
    <section className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm mx-auto max-w-xl space-y-4 py-10">
      <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-warning/10 text-warning">404</span>
      <h1 className="font-heading text-2xl font-semibold tracking-tight sm:text-3xl">Данные не найдены</h1>
      <p>По этому адресу нет доступной страницы.</p>
      <Link className="inline-flex min-h-9 items-center justify-center rounded-md border px-3 py-2 text-sm font-medium hover:bg-accent" href="/" prefetch={false}>Вернуться к обзору</Link>
    </section>
  );
}
