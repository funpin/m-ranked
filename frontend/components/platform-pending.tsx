import Link from "@/components/native-link";
import { PLATFORM_LONG_LABELS } from "@/lib/format";
import { queryHref } from "@/lib/params";
import type { Platform } from "@/lib/types";

export function PlatformPending({ platform, kind }: { platform: Platform; kind: "rating" | "compare" }) {
  const title = kind === "rating" ? "Рейтинг" : "Сравнение";
  return <>
    <h1>{title} · {PLATFORM_LONG_LABELS[platform]}</h1><p className="lead">{kind === "rating"
      ? "Рейтинг будет построен только по выбранной площадке."
      : "Сравнение будет использовать публикации и фиксированные выборки только выбранной площадки."}</p>
    <section className="panel platform-pending">
      <span className={`platform-chip platform-${platform}`}>{PLATFORM_LONG_LABELS[platform]}</span>
      <div><h2>Раздел не смешивает данные разных соцсетей</h2><p className="panel-note">Платформенный контекст уже сохранён в адресе и навигации. Данные Telegram здесь намеренно не показываются вместо выбранной площадки. Полная аналитика появится после подключения её вертикального сценария.</p></div>
      <Link className="secondary pending-back" href={queryHref("/", { platform })} prefetch={false}>Вернуться к обзору</Link>
    </section>
  </>;
}
