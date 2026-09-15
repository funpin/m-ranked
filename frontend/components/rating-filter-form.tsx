"use client";
import { beginNavigation } from "@/lib/navigation-pending";
import { useRouter } from "next/navigation";
import { useTransition, type ComponentProps } from "react";

export function RatingFilterForm(props:ComponentProps<"form">) {
  const router=useRouter();
  const [pending,startTransition]=useTransition();
  return <form {...props} aria-busy={pending} onChange={(event) => {const field=event.target;
    // Период — выпадающий список, площадка — переключатель: оба меняют
    // выборку целиком, поэтому применяются сразу, без кнопки.
    if((field instanceof HTMLSelectElement && field.name === "period")
      || (field instanceof HTMLInputElement && field.type === "radio" && field.name === "platform"))
      event.currentTarget.requestSubmit();}} onSubmit={(event) => {
    event.preventDefault();
    const query=new URLSearchParams();
    new FormData(event.currentTarget).forEach((value,key) => {if(typeof value === "string") query.append(key,value);});
    beginNavigation();
    startTransition(()=>router.push(`/rating?${query}`,{scroll:false}));
  }}>{props.children}<span className="text-xs text-muted-foreground" role="status" hidden={!pending}>Обновляю…</span></form>;
}
