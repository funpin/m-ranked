import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Link from "@/components/native-link";
import result from "../../../../research/smart-engagement-2026-09/46_max_historical_m2_shadow_2026-09-27.json";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Локальная проверка M1/M2",
  robots: { index: false, follow: false },
};

const localTime = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  timeZone: "Europe/Moscow",
});

type Example = (typeof result.event_examples_m2_less_unusual)[number];

function ExampleRow({ item, direction }: { item: Example; direction: "less" | "more" }) {
  const start = localTime.format(new Date(item.start_at));
  const end = localTime.format(new Date(item.end_at));
  return (
    <li className="border-border grid gap-3 border-t py-4 first:border-t-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="min-w-0 space-y-1">
        <p className="font-medium">{start}–{end} · +{item.delta_views} просмотров</p>
        <p className="text-muted-foreground text-sm">
          Новый пост: {item.new_post_distance}-я позиция · {item.new_post_views} просмотров
        </p>
        <Link className="text-chart-1 inline-block text-sm underline underline-offset-4" href={`/publications/${item.publication_id}`}>
          Открыть публикацию
        </Link>
      </div>
      <p className="font-mono text-sm tabular-nums sm:text-right">
        M1 {item.m1_tail_rank.toFixed(4)} <span className={direction === "less" ? "text-emerald-500" : "text-amber-500"}>→</span> M2 {item.m2_tail_rank.toFixed(4)}
      </p>
    </li>
  );
}

export default function LocalAnomalyLab() {
  if (process.env.MRANKED_RESEARCH_PREVIEW !== "enabled") notFound();
  const first = result.first_comparable_event_per_post;
  const event = result.event_paired_5pct_diagnostic;
  const less = result.event_examples_m2_less_unusual[0];
  const more = result.event_examples_m2_more_unusual[0];

  return (
    <div className="grid gap-8 pb-12">
      <header className="grid gap-3">
        <p className="text-amber-500 text-sm font-semibold">Локальный исследовательский расчёт · MAX</p>
        <h1 className="font-heading text-3xl font-bold tracking-tight sm:text-5xl">Новый анализ M1/M2 на реальных постах</h1>
        <p className="text-muted-foreground max-w-3xl text-base leading-relaxed">
          Архивная копия до 23.09.2026: {result.selected_posts} публикации, {result.selected_accounts} аккаунтов.
          M1 сравнивает прирост с постами того же возраста; M2 дополнительно учитывает новый пост, его положение в ленте и охват.
        </p>
      </header>

      <section aria-labelledby="lab-result" className="bg-card ring-foreground/10 grid gap-5 rounded-2xl p-5 ring-1 sm:p-7">
        <h2 id="lab-result" className="font-heading text-2xl font-bold">Результат контрольного периода</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="bg-muted/40 rounded-xl p-4">
            <p className="text-3xl font-bold tabular-nums">{result.holdout_event_paired_ranked.toLocaleString("ru-RU")}</p>
            <p className="text-muted-foreground text-sm">окон с новым постом, пригодных для обоих методов</p>
          </div>
          <div className="bg-muted/40 rounded-xl p-4">
            <p className="text-3xl font-bold tabular-nums">{event.m1_small_tail} → {event.m2_small_tail}</p>
            <p className="text-muted-foreground text-sm">окон с рангом ≤ 0,05: M1 → M2</p>
          </div>
          <div className="bg-muted/40 rounded-xl p-4">
            <p className="text-3xl font-bold tabular-nums">{first.m1_small_tail_posts} → {first.m2_small_tail_posts}</p>
            <p className="text-muted-foreground text-sm">первых пригодных окон у {first.posts} постов: M1 → M2</p>
          </div>
        </div>
        <p className="text-sm leading-relaxed">
          <strong>M2 пока не готов к оценке публикаций.</strong> В этом архивном прогоне он чаще относит прирост к редкому хвосту.
          Ранг ≤ 0,05 здесь диагностический: он не означает вероятность накрутки или измеренную долю ложных тревог.
        </p>
      </section>

      <section aria-labelledby="lab-examples" className="bg-card ring-foreground/10 rounded-2xl p-5 ring-1 sm:p-7">
        <h2 id="lab-examples" className="font-heading mb-2 text-2xl font-bold">Два окна из локальной копии</h2>
        <p className="text-muted-foreground mb-4 text-sm">Меньший ранг означает более редкий прирост в соответствующей группе сравнения.</p>
        <ul>
          <ExampleRow item={less} direction="less" />
          <ExampleRow item={more} direction="more" />
        </ul>
      </section>

      <p className="text-muted-foreground max-w-3xl text-sm leading-relaxed">
        В архиве отсутствуют многие успешные чтения без изменения счётчика; позиции взяты из нынешнего списка видимых постов.
        Публичные оценки не менялись. Следующая проверка требует новой когорты полных чтений и независимой разметки.
      </p>
    </div>
  );
}
