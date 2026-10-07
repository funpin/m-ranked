import bundled from "@/lib/contributors.generated.json";

/** Автор репозитория в шапке сайта. */
export type Contributor = { login: string; contributions: number; url: string; avatar: string };

/** Список, вшитый в сборку: на случай, если серверный ещё не появился. */
export const BUNDLED_CONTRIBUTORS: Contributor[] = bundled;

const LOGIN = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/;
const AVATAR = /^\/contributors\/(?:live\/[A-Za-z0-9-]{1,39}-[0-9a-f]{12}|[A-Za-z0-9-]{1,39})\.(?:png|jpg|webp)$/;

/** Запись из файла на сервере проверяется так же строго, как ввод извне. */
export function isContributor(value: unknown): value is Contributor {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Record<string, unknown>;
  return typeof item.login === "string" && LOGIN.test(item.login)
    && typeof item.contributions === "number" && Number.isSafeInteger(item.contributions) && item.contributions >= 0
    && item.url === `https://github.com/${item.login}`
    && typeof item.avatar === "string" && AVATAR.test(item.avatar);
}
