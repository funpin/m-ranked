import { PlatformChip } from "@/components/platform-chip";

import Link from "@/components/native-link";
import { PLATFORM_LONG_LABELS } from "@/lib/format";
import { queryHref } from "@/lib/params";
import type { Platform } from "@/lib/types";

export function PlatformPending({ platform, kind }: { platform: Platform; kind: "rating" | "compare" }) {
  const title = kind === "rating" ? "Рейтинг" : "Сравнение";
  return <>
    <h1 className="font-heading text-2xl font-semibold tracking-tight sm:text-3xl">{title} · {PLATFORM_LONG_LABELS[platform]}</h1><p className="mt-2 mb-5 text-sm text-muted-foreground">{kind === "rating"
      ? "Рейтинг будет построен только по выбранной площадке."
      : "Сравнение будет использовать публикации и фиксированные выборки только выбранной площадки."}</p>
    <section className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm grid gap-4">
      <PlatformChip className="w-fit" platform={platform} label={PLATFORM_LONG_LABELS[platform]} />
      <div><h2 className="font-heading text-lg font-semibold">Раздел не смешивает данные разных соцсетей</h2><p className="mt-2 text-sm leading-relaxed text-muted-foreground">Платформенный контекст уже сохранён в адресе и навигации. Данные Telegram здесь намеренно не показываются вместо выбранной площадки. Полная аналитика появится после подключения её вертикального сценария.</p></div>
      <Link className="inline-flex w-fit rounded-md border px-3 py-2 hover:bg-accent" href={queryHref("/", { platform })} prefetch={false}>Вернуться к обзору</Link>
    </section>
  </>;
}
