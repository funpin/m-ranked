"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { StatusPill } from "@/components/ui";
import { useEffect } from "react";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <Card role="alert" className="mx-auto max-w-xl py-10">
      <CardContent className="space-y-4">
        <StatusPill tone="red">Ошибка</StatusPill>
        <h1 className="font-heading text-2xl font-semibold tracking-tight sm:text-3xl">Страница временно недоступна</h1>
        <p>Не удалось получить согласованное представление данных. Повторите запрос.</p>
        <Button type="button" onClick={reset}>Повторить</Button>
      </CardContent>
    </Card>
  );
}
