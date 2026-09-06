import Link from "next/link";

export default function NotFound() {
  return (
    <section className="panel error-state">
      <span className="pill pill-amber">404</span>
      <h1>Данные не найдены</h1>
      <p>По этому адресу нет доступной страницы.</p>
      <Link className="button-link" href="/">Вернуться к обзору</Link>
    </section>
  );
}
