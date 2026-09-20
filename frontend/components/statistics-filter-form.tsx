"use client";

import { beginNavigation } from "@/lib/navigation-pending";
import { useRouter } from "next/navigation";
import { useRef, useTransition, type ComponentProps } from "react";

export function StatisticsFilterForm(props: ComponentProps<"form">) {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const [pending, startTransition] = useTransition();

  function navigate(form: HTMLFormElement) {
    const query = new URLSearchParams();
    new FormData(form).forEach((value, key) => {
      if (typeof value === "string" && value !== "") query.set(key, value);
    });
    beginNavigation();
    startTransition(() => router.push(`/statistics?${query}`, { scroll: false }));
  }

  return (
    <form
      {...props}
      ref={formRef}
      aria-busy={pending}
      onChange={(event) => {
        const field = event.target;
        if ((field instanceof HTMLSelectElement && field.name !== "q")
          || (field instanceof HTMLInputElement && field.type === "radio")) {
          event.currentTarget.requestSubmit();
        }
      }}
      onSubmit={(event) => {
        event.preventDefault();
        navigate(event.currentTarget);
      }}
    >
      {props.children}
      <span className="text-muted-foreground text-xs" role="status" hidden={!pending}>Обновляю…</span>
    </form>
  );
}
