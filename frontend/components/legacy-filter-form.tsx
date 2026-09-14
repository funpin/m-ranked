"use client";

import { useEffect, useRef, useTransition, type ComponentProps } from "react";
import { beginNavigation } from "@/lib/navigation-pending";
import { useRouter, useSearchParams } from "next/navigation";
import { normalizePlatform } from "@/lib/params";

/** Hydrates only form interaction; all labels, values and results are SSR. */
export function LegacyFilterForm({ action = "/", ...props }: ComponentProps<"form">) {
  const form = useRef<HTMLFormElement>(null);
  const query=useSearchParams();
  const router=useRouter();
  const [pending,startTransition]=useTransition();
  useEffect(() => {
    // Browser bfcache restores edited native control properties, while the URL
    // still describes the server-rendered defaults of that history entry.
    let timer: ReturnType<typeof setTimeout> | undefined;
    // HTML history restores persisted native controls after popstate/pageshow.
    const restore = () => { timer = setTimeout(() => {
      form.current?.reset();
      // Chrome can restore a radio's changed checked property after hydration.
      // Read the current URL, which is authoritative for this history entry.
      const platform=normalizePlatform(new URL(location.href).searchParams.getAll("platform"));
      form.current?.querySelectorAll<HTMLInputElement>('input[name="platform"]').forEach((radio) => {radio.checked=radio.value===platform;});
    }, 0); };
    const show = (event: PageTransitionEvent) => { if (event.persisted) restore(); };
    if ((performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined)?.type === "back_forward") restore();
    window.addEventListener("pageshow", show);
    window.addEventListener("popstate", restore);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("pageshow", show);
      window.removeEventListener("popstate", restore);
    };
  }, [query]);
  return <form {...props} action={action} aria-busy={pending} ref={form} onSubmit={(event) => {
    // Форма остаётся настоящей: без скриптов браузер отправит её сам и
    // страница перезагрузится, как раньше. Со скриптами тот же адрес
    // открывается клиентским переходом — без перезагрузки и с мгновенным
    // скелетоном вместо белого экрана.
    event.preventDefault();
    const query=new URLSearchParams();
    new FormData(event.currentTarget).forEach((value,key) => {if(typeof value === "string" && value !== "") query.append(key,value);});
    const target=typeof action === "string" ? action : "/";
    beginNavigation();
    startTransition(()=>router.push(`${target}?${query}`,{scroll:false}));
  }} onChange={(event) => {
    const field = event.target;
    if (field instanceof HTMLSelectElement && field.name === "sort") {
      const direction = event.currentTarget.elements.namedItem("direction");
      if (direction instanceof HTMLSelectElement) direction.value = field.value === "name" ? "asc" : "desc";
    }
    if (field instanceof HTMLInputElement && field.name === "platform" && field.type === "radio") {
      event.currentTarget.requestSubmit();
    }
  }}>{props.children}<span className="text-muted-foreground text-xs" role="status" hidden={!pending}>Обновляю…</span></form>;
}
