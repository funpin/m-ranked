"use client";
import { useRouter } from "next/navigation";
import { useTransition, type ComponentProps } from "react";

export function RatingFilterForm(props:ComponentProps<"form">) {
  const router=useRouter();
  const [pending,startTransition]=useTransition();
  return <form {...props} aria-busy={pending} onChange={(event) => {if(event.target instanceof HTMLSelectElement && event.target.name === "period") event.currentTarget.requestSubmit();}} onSubmit={(event) => {
    event.preventDefault();
    const query=new URLSearchParams();
    new FormData(event.currentTarget).forEach((value,key) => {if(typeof value === "string") query.append(key,value);});
    startTransition(()=>router.push(`/rating?${query}`,{scroll:false}));
  }}>{props.children}<span className="text-xs text-muted-foreground" role="status" hidden={!pending}>Обновляю…</span></form>;
}
