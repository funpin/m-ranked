import Link from "@/components/native-link";
import { accountHref } from "@/lib/entity-routes";
import { PLATFORM_LABELS } from "@/lib/format";
import type { AccountView } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Users } from "lucide-react";

const compact = new Intl.NumberFormat("ru-RU", { notation: "compact", maximumFractionDigits: 1 });
const exact = new Intl.NumberFormat("ru-RU");

function subscribersWord(value: number) {
  const n = value % 100;
  return n > 10 && n < 20 ? "подписчиков" : n % 10 === 1 ? "подписчик" : n % 10 >= 2 && n % 10 <= 4 ? "подписчика" : "подписчиков";
}

const TONE: Record<string, string> = {
  telegram: "border-platform-telegram/40 bg-platform-telegram/10 text-platform-telegram",
  vk: "border-platform-vk/40 bg-platform-vk/10 text-platform-vk",
  max: "border-platform-max/40 bg-platform-max/10 text-platform-max",
  rutube: "border-platform-rutube/40 bg-platform-rutube/10 text-platform-rutube",
};
const ORDER = ["telegram", "vk", "max", "rutube"];

/**
 * Переход между аккаунтами одного вуза.
 *
 * Раньше, чтобы посмотреть посты того же вуза в другой сети, приходилось
 * возвращаться в обзор, менять площадку и заново искать карточку. Все
 * подключённые аккаунты известны из справочника, поэтому они стоят прямо над
 * списком постов; цвет у каждой площадки свой — тот же, что на карточке.
 */
export function ChannelSwitch({ accounts, currentId }: { accounts: readonly AccountView[]; currentId: string }) {
  const siblings = [...accounts]
    .filter((account) => account.accountId)
    .sort((a, b) => ORDER.indexOf(a.platform) - ORDER.indexOf(b.platform));
  if (siblings.length < 2) return null;
  return (
    <nav className="mb-5 flex flex-wrap gap-2" aria-label="Площадки вуза">
      {siblings.map((account) => {
        const current = account.accountId === currentId;
        const label = account.title || (account.username ? `@${account.username}` : account.canonicalExternalId);
        return (
          <Link
            key={account.accountId}
            href={accountHref(account.accountId)}
            prefetch={false}
            aria-current={current ? "page" : undefined}
            className={cn(
              "inline-flex max-w-[20rem] items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs font-medium no-underline transition-colors",
              current
                ? TONE[account.platform] ?? "border-border bg-muted"
                : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <span className="font-black tracking-wide">{PLATFORM_LABELS[account.platform]}</span>
            <span className="truncate">{label}</span>
            {account.subscriberCount != null ? (
              <span data-testid="channel-subscribers" title={`${exact.format(account.subscriberCount)} ${subscribersWord(account.subscriberCount)}`}
                className={cn("ml-0.5 inline-flex shrink-0 items-center gap-1 rounded-sm px-1.5 py-0.5 text-[11px] font-semibold tabular-nums",
                  current ? "bg-background/70 text-foreground" : "bg-muted text-foreground/80")}>
                <Users aria-hidden="true" className="size-3" />{compact.format(account.subscriberCount)}
                <span className="sr-only"> {subscribersWord(account.subscriberCount)}</span>
              </span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}
