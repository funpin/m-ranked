import Link from "next/link";

export default function NotFound() {
  return (
    <section className="panel error-state">
      <span className="pill pill-amber">404</span>
      <h1>Данные не найдены</h1>
      <p>Объект отсутствует в текущей ревизии данных или его legacy-ID больше не сопоставлен.</p>
      <Link className="button-link" href="/">Вернуться к обзору</Link>
    </section>
  );
}
