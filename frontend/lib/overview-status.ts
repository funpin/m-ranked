import type { OverviewItem, OverviewPage } from "./types";

export function overviewStatus(item: Pick<OverviewItem, "platform" | "accountCount" | "enabledAccountCount" | "connectedPlatformCount" | "lastErrorCode" | "lastCheckedAt" | "statusCode">,
  warning: OverviewPage["integrationWarning"] = null): { text: string; kind: "ok" | "warn" | "bad" | "muted" } {
  if (item.platform === "telegram") return item.lastErrorCode
    ? { text: item.lastErrorCode, kind: "bad" } : { text: "активен", kind: "ok" };
  if (!item.accountCount) return { text: "Аккаунт не добавлен", kind: "muted" };
  if (!item.enabledAccountCount) return { text: "Все аккаунты отключены", kind: "warn" };
  if (item.platform === "all") return { text: `Подключено площадок: ${item.connectedPlatformCount} из 4`, kind: item.connectedPlatformCount ? "ok" : "muted" };
  if (warning) {
    // Preserve the original legacy status copy, including its shared non-MAX
    // missing-provider message. The API supplies safe flags, never credentials.
    const text = warning === "max_phone_required" ? "Нужен MAX_USER_PHONE"
      : warning === "max_session_required" ? "Нужна авторизация MAX: auth-max" : "Нужен VK_ACCESS_TOKEN";
    return { text, kind: "warn" };
  }
  if (item.lastErrorCode || item.statusCode === "last_poll_failed") return { text: "Последний опрос завершился ошибкой", kind: "bad" };
  if (item.lastCheckedAt) return { text: "активен", kind: "ok" };
  return { text: "Ожидает первого опроса", kind: "muted" };
}
