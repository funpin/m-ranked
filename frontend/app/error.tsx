"use client";

import { useEffect } from "react";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <section className="panel error-state" role="alert">
      <span className="pill pill-red">Ошибка</span>
      <h1>Страница временно недоступна</h1>
      <p>Не удалось получить согласованное представление данных. Повторите запрос.</p>
      <button type="button" onClick={reset}>Повторить</button>
    </section>
  );
}
