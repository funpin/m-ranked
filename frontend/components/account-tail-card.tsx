import { Suspense } from "react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui";
import { MethodNote } from "@/components/method-note";
import { LevelIcon } from "@/components/anomaly-icons";
import { PLATFORM_LABELS } from "@/lib/format";
import { tailSummary, type TailProfileLoad } from "@/lib/account-tail";
import { cn } from "@/lib/utils";

const METHOD = "Сравниваются доли реакций на просмотры одних и тех же постов: в первые сутки и на просмотрах, "
  + "пришедших после четырёх суток (до четырнадцати). Обычно поздние читатели реагируют реже ранних. "
  + "Порог задают другие аккаунты площадки, без этого аккаунта: не ниже их 90-го перцентиля и не меньше трёх медиан. "
  + "«Устойчиво» — отклонение есть и на более ранних, и на свежих постах, а поздние реакции приходили в разные дни двух недель. "
  + "Только точные счётчики; пропуски замеров не считаются нулями.";

/** Блок страницы аккаунта. Страница его не ждёт: пока ответ в пути — скелетон,
 *  сбой анализа — спокойная строка, а не ошибка страницы. */
export function AccountTailCard({ profile }: { profile: Promise<TailProfileLoad> }) {
  return (
    <Card as="section" className="block p-5 text-sm mt-5 min-w-0" data-testid="account-tail-card"
      aria-labelledby="account-tail-title">
      <h2 id="account-tail-title" className="font-heading flex flex-wrap items-center gap-1 text-lg font-semibold tracking-tight">
        Отклик на старые публикации <MethodNote title="Отклик на старые публикации">{METHOD}</MethodNote>
      </h2>
      <Suspense fallback={<Skeleton className="mt-3 h-20 w-full" aria-label="Профиль отклика загружается" />}>
        <Body profile={profile} />
      </Suspense>
    </Card>
  );
}

async function Body({ profile }: { profile: Promise<TailProfileLoad> }) {
  const loaded = await profile;
  if (!loaded) return <p className="text-muted-foreground mt-2 text-sm">Результат временно недоступен.</p>;
  const view = tailSummary(loaded);
  if (!view.metrics) {
    return <p className="text-muted-foreground mt-2 text-sm" data-testid="account-tail-status">{view.label}</p>;
  }
  const metrics = view.metrics;
  const tone = view.level === null || view.level === 0 ? null : view.level === 2 ? "amber" : "neutral";
  return <div className="mt-3 grid gap-4">
    <div className="flex flex-wrap items-center gap-2" data-testid="account-tail-status">
      {tone ? <StatusPill tone={tone}><LevelIcon level={view.level === 2 ? 2 : 1} className={cn("size-3.5", view.level === 1 && "text-chart-3")} />{view.label}</StatusPill>
        : <span className="inline-flex items-center gap-1.5 font-semibold"><LevelIcon level={view.level === null ? null : 0} className="text-muted-foreground size-4" />{view.label}</span>}
      <span className="text-muted-foreground text-xs">
        {loaded.platform ? `среди аккаунтов ${PLATFORM_LABELS[loaded.platform]}` : null}{view.window ? ` · ${view.window}` : null}
      </span>
    </div>
    {view.abstainText ? <p className="text-muted-foreground text-sm">{view.abstainText}</p> : null}
    <dl className="grid gap-3 sm:grid-cols-3">
      <Figure label="реакций на 100 просмотров в первые сутки" value={view.earlyRate} />
      <Figure label="реакций на 100 просмотров после 4 суток" value={view.lateRate} />
      <Figure label={view.cohortText ?? "поздняя доля к ранней"} value={view.ratio} highlight={tone !== null} />
    </dl>
    <p className="text-sm leading-relaxed">{view.sentence}</p>
    {metrics.days.length ? <DailyStrip days={metrics.days} /> : null}
    <p className="text-muted-foreground text-xs leading-relaxed">{loaded.disclaimer}</p>
  </div>;
}

function Figure({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return <div className="grid min-w-0 content-start gap-1 rounded-lg border p-3">
    <dd className={cn("font-heading tabular text-2xl font-bold leading-none", highlight && "text-chart-3")}>{value}</dd>
    <dt className="text-muted-foreground text-xs">{label}</dt>
  </div>;
}

/** Сутки окна: сколько старых постов под наблюдением получили реакции. Серые —
 *  замеров не хватило, это неизвестность, а не тишина. */
function DailyStrip({ days }: { days: { day: string; observed: number; active: number; reactions: number }[] }) {
  return <figure className="grid gap-1.5">
    <div className="flex h-12 items-end gap-[3px]" role="img"
      aria-label={`Сутки с поздними реакциями: ${days.filter((day) => day.active > 0).length} из ${days.length}`}>
      {days.map((day) => {
        const share = day.observed ? day.active / day.observed : 0;
        return <span key={day.day} title={day.observed
          ? `${day.day}: реакции получили ${day.active} из ${day.observed} старых постов, +${day.reactions}`
          : `${day.day}: замеров старых постов не хватило`}
          className={cn("min-w-0 flex-1 rounded-sm", day.observed ? "bg-chart-3" : "bg-muted")}
          style={{ height: day.observed ? `${Math.max(8, share * 100)}%` : "100%", opacity: day.observed ? 0.35 + 0.65 * share : 0.5 }} />;
      })}
    </div>
    <figcaption className="text-muted-foreground text-xs">
      Доля старых постов (4–14 суток), получивших реакции за сутки; серым — сутки без достаточных замеров.
    </figcaption>
  </figure>;
}
