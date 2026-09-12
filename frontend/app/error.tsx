"use client";
import { NativeButton } from "@/components/native-field";

import { useEffect } from "react";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <section className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm mx-auto max-w-xl space-y-4 py-10" role="alert">
      <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-destructive/10 text-destructive">Ошибка</span>
      <h1 className="font-heading text-2xl font-semibold tracking-tight sm:text-3xl">Страница временно недоступна</h1>
      <p>Не удалось получить согласованное представление данных. Повторите запрос.</p>
      <NativeButton type="button" onClick={reset}>Повторить</NativeButton>
    </section>
  );
}
