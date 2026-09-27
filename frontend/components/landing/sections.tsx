import type { CSSProperties, ReactNode } from "react";
import { ArrowDown, ArrowRight, ArrowUpRight, BookOpen, Braces, Check, CircleSlash, X } from "lucide-react";
import Link from "@/components/native-link";
import { GithubMark } from "@/components/github-mark";
import { PlatformLogo } from "@/components/platform-logo";
import { COLLECTION_SCHEDULE, KNOWN_PLATFORMS, TRACKING_DAYS, countWithUnit, formatStat, isKnownPlatform, type SiteSummary } from "@/lib/landing";
import { REPOSITORY_URL } from "@/lib/repository";
import { cn } from "@/lib/utils";
import { HeroScene } from "./hero-scene";
import { Ribbon } from "./ribbon";

export type LandingPlatform = { platform: string; accounts: number | null };

const brand = (platform: string) => ({ "--brand": isKnownPlatform(platform) ? `var(--platform-${platform})` : "var(--chart-2)" }) as CSSProperties;
const platformName = (platform: string) => (isKnownPlatform(platform) ? KNOWN_PLATFORMS[platform].name : platform);

/** Заголовок раздела в духе страниц Apple: серая подпись, крупный заголовок
 *  по центру и вводный абзац, где главное выделено цветом текста. */
export function SectionHead({ eyebrow, title, children, id }: {
  eyebrow: string; title: ReactNode; children?: ReactNode; id?: string;
}) {
  return (
    <header className="mx-auto grid max-w-4xl justify-items-center gap-5 text-center">
      <p className="landing-rise text-muted-foreground text-base font-semibold sm:text-lg">{eyebrow}</p>
      <h2 id={id} className="landing-rise font-heading text-4xl leading-[1.04] font-bold tracking-[-0.025em] text-balance sm:text-6xl lg:text-7xl">{title}</h2>
      {children && <p className="landing-rise text-muted-foreground max-w-3xl text-lg leading-relaxed text-pretty sm:text-xl [&_b]:text-foreground [&_b]:font-semibold">{children}</p>}
    </header>
  );
}

export function Hero({ platforms }: { platforms: readonly LandingPlatform[] }) {
  return (
    // Первый экран занимает всё окно под шапкой: сводка с цифрами начинается
    // ниже и появляется только при прокрутке.
    <section aria-labelledby="landing-title" className="relative isolate -mt-6 flex min-h-[calc(100svh-3.5rem)] flex-col justify-center py-16">
      <div className="landing-bleed landing-hero-parallax absolute inset-y-0 -z-10 overflow-hidden" aria-hidden="true">
        <HeroScene />
        <div className="landing-hero-veil absolute inset-0" />
      </div>
      <div className="landing-hero-copy grid max-w-5xl gap-7">
        <p className="text-muted-foreground inline-flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-medium tracking-[0.12em] uppercase">
          <span className="relative flex size-2" aria-hidden="true">
            <span className="bg-chart-1 absolute inline-flex size-full animate-ping rounded-full opacity-60 motion-reduce:hidden" />
            <span className="bg-chart-1 relative inline-flex size-2 rounded-full" />
          </span>
          Сбор идёт круглосуточно
          {platforms.map(({ platform }) => (
            <span key={platform} className="inline-flex items-center gap-2"><span aria-hidden="true">·</span>{platformName(platform)}</span>
          ))}
        </p>
        <h1 id="landing-title" className="font-heading text-[clamp(3rem,10vw,7.5rem)] leading-[0.92] font-bold tracking-[-0.035em]">
          Соцсети вузов.<br /><span className="landing-gradient-text">Как есть.</span>
        </h1>
        <p className="text-muted-foreground max-w-xl text-lg leading-relaxed text-pretty sm:text-xl">
          Замеряем публикации официальных аккаунтов российских вузов с первых минут и показываем, как набираются
          просмотры. Код открыт.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Link href="/rating" prefetch={false} data-testid="landing-cta"
            className="group bg-foreground text-background focus-visible:ring-ring/50 inline-flex h-12 items-center gap-2 rounded-full px-6 text-sm font-semibold shadow-lg shadow-black/10 transition-transform outline-none hover:-translate-y-0.5 focus-visible:ring-4 active:translate-y-0">
            Открыть рейтинг
            <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
          </Link>
          <a href="#how"
            className="group text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 inline-flex h-12 items-center gap-2 rounded-full px-4 text-sm font-medium transition-colors outline-none focus-visible:ring-4">
            Как это устроено
            <ArrowDown className="size-4 transition-transform group-hover:translate-y-0.5" aria-hidden="true" />
          </a>
        </div>
      </div>
    </section>
  );
}

/** Цифры проекта — как характеристики на страницах Apple: тонкая линия
 *  сверху, подпись, крупное число и пояснение. Досчитывают при прокрутке. */
export function Stats({ summary }: { summary: SiteSummary }) {
  const items = [
    { value: summary.institutions, label: "Под наблюдением", caption: "вузов" },
    { value: summary.accounts, label: "Официальных", caption: "аккаунтов в соцсетях" },
    { value: summary.publications, label: "Публикаций", caption: "с полной историей замеров" },
    { value: summary.snapshots, label: "Сохранено", caption: "замеров счётчиков" },
  ].filter((item): item is { value: number; label: string; caption: string } => item.value !== null);
  return (
    <section aria-label="Проект в цифрах" className="mx-auto w-full max-w-6xl py-24 sm:py-36" data-testid="landing-stats">
      <dl className="grid grid-cols-2 gap-x-8 gap-y-12 lg:grid-cols-4">
        {items.map((item, index) => (
          <div key={item.label} className="landing-pop grid content-start gap-1.5 border-t pt-6" style={{ "--i": index } as CSSProperties}>
            <dt className="text-muted-foreground text-sm">{item.label}</dt>
            <dd className="font-heading text-5xl font-bold tracking-tight tabular-nums sm:text-6xl" data-count={item.value}>{formatStat(item.value)}</dd>
            <dd className="text-muted-foreground text-sm">{item.caption}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function Platforms({ platforms, phone }: { platforms: readonly LandingPlatform[]; phone: ReactNode }) {
  return (
    <section aria-labelledby="landing-platforms" className="grid grid-cols-1 gap-14 py-24 sm:py-36">
      <SectionHead id="landing-platforms" eyebrow="Площадки" title={<>Несколько площадок.<br />Одна шкала.</>}>
        У каждой площадки свои счётчики. Мы берём <b>только публичные цифры, которые видит любой читатель,</b> и
        приводим их к общему виду, чтобы вузы можно было честно сравнить.
      </SectionHead>
      {phone}
      <Ribbon label="Площадки" fit>
        <ul role="list" className="contents" data-testid="landing-platforms">
          {platforms.map(({ platform, accounts }, index) => {
            const known = isKnownPlatform(platform) ? KNOWN_PLATFORMS[platform] : null;
            return (
              <li key={platform} style={{ ...brand(platform), "--i": index } as CSSProperties}
                className="landing-ribbon-item landing-slide landing-tile landing-platform relative flex w-[min(78vw,330px)] shrink-0 snap-start flex-col gap-6 overflow-hidden p-7 sm:p-8 lg:w-auto">
                <div className="grid gap-5">
                  {isKnownPlatform(platform)
                    ? <PlatformLogo platform={platform} size={56} decorative className="landing-platform-logo rounded-2xl" />
                    : <span className="bg-muted grid size-14 place-items-center rounded-2xl text-lg font-bold">{platform.slice(0, 2).toUpperCase()}</span>}
                  <h3 className="font-heading text-3xl font-bold tracking-tight">{platformName(platform)}</h3>
                </div>
                <div className="flex flex-1 flex-col gap-4">
                  {accounts !== null && (
                    <p className="font-heading text-5xl font-bold tracking-tight tabular-nums" style={{ color: "var(--brand)" }}>
                      {formatStat(accounts)}
                      <span className="text-muted-foreground block pt-1 font-sans text-sm font-medium tracking-normal">{countWithUnit(accounts, known?.unit ?? "аккаунт").replace(/^[\d\s\u00a0]+/, "")}</span>
                    </p>
                  )}
                  {known && (
                    <ul className="mt-auto flex flex-wrap gap-1.5" aria-label={`Счётчики ${known.name}`}>
                      {known.metrics.map((metric) => (
                        <li key={metric} className="bg-foreground/[0.06] text-muted-foreground rounded-full px-2.5 py-1 text-xs">{metric}</li>
                      ))}
                    </ul>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </Ribbon>
    </section>
  );
}

/** Полоса плотности замеров: чем моложе пост, тем чаще штрихи. */
function ScheduleBar() {
  const spacing = [3, 6, 10, 18];
  return (
    <div className="grid gap-2">
      <div className="flex h-10 gap-1 overflow-hidden rounded-lg" aria-hidden="true">
        {COLLECTION_SCHEDULE.map((segment, index) => (
          <div key={segment.age} className="landing-ticks flex-1 rounded-md"
            style={{ "--tick-gap": `${spacing[index]}px`, animationDelay: `${index * 120}ms` } as CSSProperties} />
        ))}
      </div>
      <dl className="grid grid-cols-4 gap-1 text-[11px] leading-tight">
        {COLLECTION_SCHEDULE.map((segment) => (
          <div key={segment.age} className="grid gap-0.5">
            <dt className="text-muted-foreground">{segment.age}</dt>
            <dd className="font-mono font-medium">{segment.step}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Ступеньки: строка пишется только при изменении счётчика. */
function ChangesOnly() {
  const steps: [number, number][] = [[8, 76], [40, 58], [64, 44], [104, 36], [150, 30], [214, 26]];
  let d = `M${steps[0]![0]} ${steps[0]![1]}`;
  for (let index = 1; index < steps.length; index += 1) d += `H${steps[index]![0]}V${steps[index]![1]}`;
  d += "H292";
  return (
    <svg viewBox="0 0 300 90" className="h-24 w-full" aria-hidden="true">
      <path d={d} fill="none" stroke="var(--chart-2)" strokeWidth={2} className="landing-draw" pathLength={1} />
      {steps.map(([x, y]) => <circle key={x} cx={x} cy={y} r={3.5} fill="var(--chart-2)" />)}
      <circle cx={262} cy={26} r={3.5} fill="var(--background)" stroke="var(--chart-2)" strokeWidth={1.5} />
    </svg>
  );
}

function QualityRows() {
  const rows = [
    { text: "точное значение", result: "в расчётах", ok: true },
    { text: "сброс счётчика площадкой", result: "исключено", ok: false },
    { text: "недостоверное значение", result: "исключено", ok: false },
  ];
  return (
    <ul className="grid gap-1.5 text-xs">
      {rows.map((row) => (
        <li key={row.text} className="bg-muted/50 flex items-center justify-between gap-3 rounded-lg px-3 py-2">
          <span>{row.text}</span>
          <span className={cn("inline-flex items-center gap-1 font-medium", row.ok ? "landing-tone-text" : "text-muted-foreground")}>
            {row.ok ? <Check className="size-3.5" aria-hidden="true" /> : <CircleSlash className="size-3.5" aria-hidden="true" />}{row.result}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Фрагмент истории замеров поста — то, что видно на его странице и в API. */
function HistoryRows() {
  const rows = [
    ["12:05", "1 204", "+318"], ["12:10", "1 377", "+173"], ["12:15", "1 462", "+85"], ["12:30", "1 530", "+68"],
  ] as const;
  return (
    <div className="ring-foreground/10 overflow-hidden rounded-xl text-xs ring-1">
      <div className="bg-muted/50 text-muted-foreground grid grid-cols-3 px-3 py-1.5 text-[11px] tracking-wide uppercase">
        <span>замер</span><span className="text-right">просмотры</span><span className="text-right">прирост</span>
      </div>
      {rows.map(([time, views, delta]) => (
        <div key={time} className="grid grid-cols-3 border-t px-3 py-1.5 font-mono tabular-nums">
          <span className="text-muted-foreground">{time}</span><span className="text-right">{views}</span>
          <span className="landing-tone-text text-right">{delta}</span>
        </div>
      ))}
    </div>
  );
}

const STEPS = [
  {
    title: "Замер с первых минут",
    text: <>Чем моложе пост, тем чаще он замеряется: начало роста не теряется. Через {TRACKING_DAYS} суток сбор
      по посту завершается.</>,
    visual: <ScheduleBar />,
  },
  {
    title: "Пишем только изменения",
    text: <>Не изменился счётчик — новая строка не пишется: ровный участок графика значит «ничего не поменялось».
      Раз в сутки — контрольный снимок.</>,
    visual: <ChangesOnly />,
  },
  {
    title: "Проверяем качество",
    text: <>Сбросы и недостоверные значения в расчёты не попадают. Пропуски сбора не маскируются: они отмечены на
      графике и сверены с журналом циклов.</>,
    visual: <QualityRows />,
  },
  {
    title: "Каждое число — с историей",
    text: <>На странице поста — все замеры по времени, пропуски сбора и вывод анализа. Тот же ряд отдаёт открытый API:
      любую цифру на сайте можно пересчитать.</>,
    visual: <HistoryRows />,
  },
] as const;

export function Pipeline({ chart }: { chart: ReactNode }) {
  return (
    <section aria-labelledby="how" className="grid grid-cols-1 scroll-mt-24 gap-14 py-24 sm:py-36">
      <SectionHead id="how" eyebrow="Как это устроено" title={<>От публикации<br />до графика</>}>
        Сборщики обходят аккаунты вузов по расписанию, <b>сохраняют историю каждого счётчика</b> и отправляют её на
        витрину, где из неё строятся рейтинг, графики и анализ.
      </SectionHead>
      <Ribbon label="Этапы">
        <ol role="list" className="contents">
          {STEPS.map((step, index) => (
            <li key={step.title} className="landing-ribbon-item landing-slide grid w-[min(84vw,440px)] shrink-0 snap-start content-start gap-5"
              style={{ "--i": index } as CSSProperties}>
              <div className="landing-tile grid min-h-[260px] content-center p-7">{step.visual}</div>
              <p className="text-muted-foreground px-1 text-base leading-relaxed text-pretty">
                <b className="text-foreground font-semibold">{step.title}.</b> {step.text}
              </p>
            </li>
          ))}
        </ol>
      </Ribbon>
      {/* Большая плитка сначала стоит с отступами по бокам и раскрывается
          на всю ширину, когда доезжает до середины экрана. */}
      <div className="landing-bleed relative px-3 sm:px-4">
        <div className="landing-widen landing-tile landing-tile-wide grid gap-6 px-6 py-10 sm:px-12 sm:py-16">
          <div className="grid justify-items-center gap-3 text-center">
            <h3 className="font-heading text-3xl font-bold tracking-tight sm:text-5xl">И вот что получается</h3>
            <Link href="/compare" prefetch={false} className="group text-chart-2 inline-flex items-center gap-1 text-base font-medium hover:underline">
              Все графики — в сравнении<ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
            </Link>
          </div>
          <div className="mx-auto w-full max-w-[1300px]">{chart}</div>
        </div>
      </div>
    </section>
  );
}

export function Rhythm({ chart }: { chart: ReactNode }) {
  return (
    <section aria-labelledby="landing-rhythm" className="grid grid-cols-1 gap-12 py-24 sm:py-36">
      <SectionHead id="landing-rhythm" eyebrow="Ритм площадок" title="Когда публикуют и что это даёт">
        Сколько публикаций выходит в каждый час и день недели, <b>сколько типичный пост набирает за первые сутки</b> и
        чем заканчивается проверка динамики — по живым данным за 30 дней.
      </SectionHead>
      {chart}
    </section>
  );
}

export function Analysis({ corridor }: { corridor: ReactNode }) {
  return (
    <section aria-labelledby="landing-analysis" className="grid grid-cols-1 gap-14 py-24 sm:py-36">
      <SectionHead id="landing-analysis" eyebrow="Автоматический анализ" title="Каждый пост проверяется">
        Пока идёт сбор, анализатор сверяет рост поста с обычным разбросом постов того же возраста на той же площадке.
        <b> Живой шум — норма:</b> сигналом становится только необычная форма роста. Её сила — повод присмотреться, а не
        вывод.
      </SectionHead>
      {/* Схема «поднимается» из наклона, как устройство на страницах Apple. */}
      <div className="landing-tilt mx-auto w-full max-w-6xl">{corridor}</div>
      <aside className="landing-rise mx-auto grid max-w-3xl gap-3 text-center">
        <p className="font-heading text-xl font-bold tracking-tight">Рядом с каждым результатом — объяснения, которые данные не исключают</p>
        <p className="text-muted-foreground text-base leading-relaxed">
          Например, пост долго показывался в рекомендациях с ровным притоком или у аккаунта крупная аудитория со
          сглаженным трафиком.
        </p>
      </aside>
    </section>
  );
}

function VerifyCard({ href, external, tone, icon, title, text, action, children, testId }: {
  href: string; external?: boolean; tone: string; icon: ReactNode; title: string; text: string; action: string;
  children: ReactNode; testId: string;
}) {
  const body = (
    <>
      <div className="landing-verify-visual bg-foreground/[0.04] relative h-40 overflow-hidden rounded-2xl" aria-hidden="true">{children}</div>
      <div className="grid gap-2">
        <span className="landing-tone-text inline-flex items-center gap-2 text-sm font-medium">{icon}{action}</span>
        <h3 className="font-heading text-2xl font-bold tracking-tight">{title}</h3>
        <p className="text-muted-foreground text-sm leading-relaxed">{text}</p>
      </div>
      <span className="text-foreground mt-auto inline-flex items-center gap-1 text-sm font-medium">
        {external ? "Открыть на GitHub" : "Читать"}
        {external
          ? <ArrowUpRight className="size-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" aria-hidden="true" />
          : <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />}
      </span>
    </>
  );
  const className = "landing-pop landing-verify landing-tile group focus-visible:ring-ring/60 relative flex flex-col gap-6 p-5 outline-none focus-visible:ring-2 sm:p-6";
  const style = { "--brand": tone, "--tone": tone } as CSSProperties;
  return external
    ? <a href={href} target="_blank" rel="noopener noreferrer" className={className} style={style} data-testid={testId}>{body}</a>
    : <Link href={href} prefetch={false} className={className} style={style} data-testid={testId}>{body}</Link>;
}

export function Verify({ summary, origin }: { summary: SiteSummary | null; origin: string }) {
  const sample = summary?.available
    ? [["institutions", summary.institutions], ["accounts", summary.accounts], ["publications", summary.publications]] as const
    : [["available", false]] as const;
  return (
    <section aria-labelledby="landing-verify" className="grid grid-cols-1 gap-14 py-24 sm:py-36">
      <SectionHead id="landing-verify" eyebrow="Прозрачность" title="Проверьте всё сами">
        <b>Код сборщиков, анализатора и сайта открыт.</b> Любой расчёт можно повторить: тот же API отдаёт замеры, из
        которых строятся графики.
      </SectionHead>
      <div className="mx-auto grid w-full max-w-6xl gap-4 lg:grid-cols-3">
        <VerifyCard href="/methodology" tone="var(--chart-1)" icon={<BookOpen className="size-4" />} action="Методология"
          title="Как мы считаем" text="Расписание замеров, качество данных, сравнение в одном возрасте и уровни анализа." testId="verify-methodology">
          <div className="absolute inset-5 grid content-start gap-2.5">
            {[92, 70, 84, 56, 76].map((width, index) => (
              <span key={index} className="landing-doc-line bg-foreground/10 h-2.5 rounded-full" style={{ width: `${width}%`, transitionDelay: `${index * 50}ms` }} />
            ))}
          </div>
          <span className="landing-doc-mark absolute top-5 left-3 h-2.5 w-1 rounded-full" style={{ background: "var(--chart-1)" }} />
        </VerifyCard>
        <VerifyCard href="/methodology/api" tone="var(--chart-2)" icon={<Braces className="size-4" />} action="Открытый API"
          title="Данные машинам" text="История каждого поста, рейтинг и сравнение — в машиночитаемом виде, без ключей." testId="verify-api">
          <pre className="absolute inset-4 overflow-hidden font-mono text-[11px] leading-5">
            <span className="text-muted-foreground">$ curl {origin.replace(/^https:\/\//, "")}/api/v1/site/summary</span>{"\n"}
            <span className="landing-json">
              {"{"}{"\n"}
              {sample.map(([key, value], index) => (
                <span key={key} className="landing-json-line" style={{ transitionDelay: `${index * 80}ms` }}>
                  {"  "}<span style={{ color: "var(--chart-2)" }}>&quot;{key}&quot;</span>: {String(value)}{index < sample.length - 1 ? "," : ""}{"\n"}
                </span>
              ))}
              {"}"}<span className="landing-caret" />
            </span>
          </pre>
        </VerifyCard>
        <VerifyCard href={REPOSITORY_URL} external tone="var(--chart-4)" icon={<GithubMark className="size-4" />} action="Исходный код"
          title="Всё в одном репозитории" text="Сборщики, база, анализ и сайт. Любую формулу можно прочитать и проверить." testId="verify-source">
          <svg viewBox="0 0 320 160" className="absolute inset-0 h-full w-full" preserveAspectRatio="xMidYMid meet">
            <path d="M24 110H296" stroke="var(--border)" strokeWidth={2} />
            <path d="M92 110C120 110 120 60 150 60H232C262 60 262 110 290 110" fill="none" stroke="var(--chart-4)" strokeOpacity={0.25} strokeWidth={2} strokeDasharray="4 6" />
            <path d="M92 110C120 110 120 60 150 60H232C262 60 262 110 290 110" fill="none" stroke="var(--chart-4)" strokeWidth={2} className="landing-branch" pathLength={1} />
            {[24, 58, 92, 190, 296].map((x) => <circle key={x} cx={x} cy={110} r={6} fill="var(--card)" stroke="var(--muted-foreground)" strokeWidth={2} />)}
            {[150, 232].map((x) => <circle key={x} cx={x} cy={60} r={6} fill="var(--card)" stroke="var(--chart-4)" strokeWidth={2} className="landing-branch-dot" />)}
          </svg>
        </VerifyCard>
      </div>
    </section>
  );
}

export function LandingFooter() {
  return (
    <footer className="text-muted-foreground border-t py-10 text-xs">
      m-ranked — открытый проект. Данные — публичные счётчики площадок; снимки хранятся с первых минут жизни поста.
    </footer>
  );
}

export function ChartUnavailable() {
  return (
    <div className="text-muted-foreground flex h-[240px] items-center justify-center gap-2 rounded-2xl border border-dashed text-sm">
      <X className="size-4" aria-hidden="true" />Живые графики сейчас недоступны — загляните чуть позже.
    </div>
  );
}

