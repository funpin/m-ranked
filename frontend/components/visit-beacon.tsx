"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

const ENDPOINT = "/api/v1/visit";
const HEARTBEAT_MS = 60_000;

/** Служебные страницы и автоматизированные браузеры не считаются. */
function counted(path: string) {
  return !path.startsWith("/manage") && !navigator.webdriver;
}

function send(view: boolean) {
  const body = view ? '{"view":true}' : "{}";
  // sendBeacon не держит страницу и не требует ответа; там, где его нет, —
  // обычный запрос с keepalive. Ошибки не важны: счётчик необязателен.
  if (navigator.sendBeacon?.(ENDPOINT, body)) return;
  void fetch(ENDPOINT, { method: "POST", body, keepalive: true, headers: { "Content-Type": "text/plain" } }).catch(() => {});
}

/**
 * Счётчик посещений без cookie: просмотр при каждом переходе и сигнал раз в
 * минуту, пока вкладка видна, — по нему панель видит, сколько людей на сайте
 * сейчас. Ни идентификатора, ни хранилища в браузере: посетителя на сервере
 * узнают по хешу адреса и браузера с солью, которая живёт одни сутки.
 */
export function VisitBeacon() {
  const pathname = usePathname();
  useEffect(() => {
    if (counted(pathname)) send(true);
  }, [pathname]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && counted(window.location.pathname)) send(false);
    }, HEARTBEAT_MS);
    return () => window.clearInterval(timer);
  }, []);
  return null;
}
