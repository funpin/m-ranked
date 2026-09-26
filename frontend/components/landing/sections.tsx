import type { CSSProperties, ReactNode } from "react";
import { ArrowDown, ArrowRight, ArrowUpRight, BookOpen, Braces, Check, CircleSlash, Server, X } from "lucide-react";
import Link from "@/components/native-link";
import { GithubMark } from "@/components/github-mark";
import { PlatformLogo } from "@/components/platform-logo";
import {
  COLLECTION_SCHEDULE, KNOWN_PLATFORMS, RUTUBE_SCHEDULE, TRACKING_DAYS, countWithUnit, isKnownPlatform,
  summaryDate, type SiteSummary,
} from "@/lib/landing";
import { REPOSITORY_URL } from "@/lib/repository";
import { cn } from "@/lib/utils";
import { CountUp } from "./count-up";
import { HeroScene } from "./hero-scene";

export type LandingPlatform = { platform: string; accounts: number | null };

const brand = (platform: string) => ({ "--brand": isKnownPlatform(platform) ? `var(--platform-${platform})` : "var(--chart-2)" }) as CSSProperties;
const platformName = (platform: string) => (isKnownPlatform(platform) ? KNOWN_PLATFORMS[platform].name : platform);

/** Заголовок раздела: подпись, крупный заголовок и вводный абзац. */
export function SectionHead({ eyebrow, title, children, tone = "var(--chart-2)", id }: {
  eyebrow: string; title: ReactNode; children?: ReactNode; tone?: string; id?: string;
}) {
  return (
    <header className="landing-reveal grid max-w-3xl gap-5">
      <p className="text-muted-foreground inline-flex items-center gap-2 text-xs font-medium tracking-[0.14em] uppercase">
        <span className="size-1.5 rounded-full" style={{ background: tone }} aria-hidden="true" />{eyebrow}
      </p>
      <h2 id={id} className="font-heading text-4xl leading-[1.02] font-bold tracking-tight text-balance sm:text-6xl">{title}</h2>
      {children && <p className="text-muted-foreground max-w-2xl text-base leading-relaxed text-pretty sm:text-lg">{children}</p>}
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
          m-ranked следит за официальными аккаунтами российских вузов, замеряет каждую публикацию с первых минут и
          показывает, как на самом деле набираются просмотры, — с открытым кодом и понятной методологией.
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

export function Stats({ summary }: { summary: SiteSummary }) {
  const items = [
    { value: summary.institutions, label: "вузов под наблюдением" },
    { value: summary.accounts, label: "официальных аккаунтов" },
    { value: summary.publications, label: "публикаций с историей" },
    { value: summary.snapshots, label: "сохранённых замеров" },
  ].filter((item): item is { value: number; label: string } => item.value !== null);
  return (
    <section aria-label="Проект в цифрах" className="landing-reveal relative pt-16 sm:pt-24" data-testid="landing-stats">
      <div className="bg-card/80 ring-foreground/10 grid grid-cols-2 overflow-hidden rounded-3xl shadow-2xl shadow-black/5 ring-1 backdrop-blur-xl lg:grid-cols-4">
        {items.map((item, index) => (
          <div key={item.label} className={cn("grid gap-1 p-6 sm:p-8", index % 2 && "border-l", index >= 2 && "border-t lg:border-t-0", index === 2 && "lg:border-l")}>
            <span className="font-heading text-4xl font-bold tracking-tight tabular-nums sm:text-5xl"><CountUp value={item.value} /></span>
            <span className="text-muted-foreground text-sm">{item.label}</span>
          </div>
        ))}
      </div>
      {summary.computedAt && (
        <p className="text-muted-foreground mt-3 px-2 text-xs">Пересчитывается раз в сутки · данные на {summaryDate(summary.computedAt)}</p>
      )}
    </section>
  );
}

export function Platforms({ platforms }: { platforms: readonly LandingPlatform[] }) {
  return (
    <section aria-labelledby="landing-platforms" className="grid gap-12 py-24 sm:py-32">
      <SectionHead id="landing-platforms" eyebrow="площадки" title={<>Несколько площадок.<br />Одна шкала.</>}>
        У каждой площадки свои счётчики. Мы берём только публичные цифры, которые видит любой читатель, и приводим их к
        общему виду, чтобы вузы можно было честно сравнить. Новая площадка подключается как ещё один сборщик.
      </SectionHead>
      <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-testid="landing-platforms">
        {platforms.map(({ platform, accounts }, index) => {
          const known = isKnownPlatform(platform) ? KNOWN_PLATFORMS[platform] : null;
          return (
            <li key={platform} style={{ ...brand(platform), animationDelay: `${index * 60}ms` }}
              className="landing-reveal landing-platform bg-card ring-foreground/10 relative grid content-start gap-5 overflow-hidden rounded-3xl p-6 ring-1">
              <div>
                {isKnownPlatform(platform)
                  ? <PlatformLogo platform={platform} size={48} decorative className="landing-platform-logo rounded-xl" />
                  : <span className="bg-muted grid size-12 place-items-center rounded-xl text-lg font-bold">{platform.slice(0, 2).toUpperCase()}</span>}
              </div>
              <div className="grid gap-1">
                <h3 className="font-heading text-2xl font-bold tracking-tight">{platformName(platform)}</h3>
                {accounts !== null && (
                  <p className="text-sm font-medium" style={{ color: "var(--brand)" }}>{countWithUnit(accounts, known?.unit ?? "аккаунт")}</p>
                )}
              </div>
              {known && (
                <ul className="flex flex-wrap gap-1.5" aria-label={`Счётчики ${known.name}`}>
                  {known.metrics.map((metric) => (
                    <li key={metric} className="bg-muted/70 text-muted-foreground rounded-full px-2.5 py-1 text-xs">{metric}</li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
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

function TwoServers() {
  return (
    <div className="grid gap-3 text-xs">
      <div className="flex items-center gap-3">
        <span className="bg-muted/60 inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 font-medium"><Server className="size-3.5" aria-hidden="true" />сбор</span>
        <span className="landing-wire relative h-px flex-1" aria-hidden="true"><span className="landing-packet" /></span>
        <span className="bg-muted/60 inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 font-medium"><Server className="size-3.5" aria-hidden="true" />витрина</span>
      </div>
      <p className="text-muted-foreground">Пакеты идут по защищённому каналу, каждый принимается ровно один раз.</p>
    </div>
  );
}

const STEPS = [
  {
    title: "Замер с первых минут",
    text: <>Чем моложе пост, тем чаще он замеряется: начало роста не теряется. Rutube — реже, {RUTUBE_SCHEDULE}.
      Через {TRACKING_DAYS} суток сбор по посту завершается.</>,
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
    title: "Сбор отделён от витрины",
    text: <>Сборщики работают на своём сервере и не зависят от посещаемости сайта; витрина получает готовые пакеты.</>,
    visual: <TwoServers />,
  },
] as const;

export function Pipeline({ chart }: { chart: ReactNode }) {
  return (
    <section aria-labelledby="how" className="grid scroll-mt-24 gap-12 py-24 sm:py-32">
      <SectionHead id="how" eyebrow="как это устроено" tone="var(--chart-1)" title={<>От публикации<br />до графика</>}>
        Сборщики обходят аккаунты вузов по расписанию, сохраняют историю каждого счётчика и отправляют её на витрину,
        где из неё строятся рейтинг, графики и анализ.
      </SectionHead>
      <ol className="grid gap-4 md:grid-cols-2">
        {STEPS.map((step, index) => (
          <li key={step.title} className="landing-reveal bg-card ring-foreground/10 grid content-start gap-5 rounded-3xl p-6 ring-1 sm:p-8">
            <div className="grid gap-2">
              <span className="text-muted-foreground font-mono text-xs">0{index + 1}</span>
              <h3 className="font-heading text-xl font-bold tracking-tight sm:text-2xl">{step.title}</h3>
              <p className="text-muted-foreground text-sm leading-relaxed">{step.text}</p>
            </div>
            {step.visual}
          </li>
        ))}
      </ol>
      <div className="landing-reveal bg-card ring-foreground/10 grid gap-5 rounded-3xl p-6 ring-1 sm:p-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h3 className="font-heading text-2xl font-bold tracking-tight">И вот что получается</h3>
          <Link href="/compare" prefetch={false} className="group text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm font-medium transition-colors">
            Все графики — в сравнении<ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
          </Link>
        </div>
        {chart}
      </div>
    </section>
  );
}

export function SameAge({ chart }: { chart: ReactNode }) {
  return (
    <section aria-labelledby="landing-age" className="grid gap-12 py-24 sm:py-32">
      <SectionHead id="landing-age" eyebrow="сравнение" tone="var(--chart-3)" title="Сравниваем в одном возрасте">
        У вчерашнего поста просмотров всегда меньше, чем у позавчерашнего, — он просто моложе. Поэтому вузы сравниваются
        по значению на одном и том же часу жизни поста: через час, сутки, неделю.
      </SectionHead>
      <div className="landing-reveal bg-card ring-foreground/10 grid gap-4 rounded-3xl p-6 ring-1 sm:p-8">
        {chart}
        <p className="text-muted-foreground text-xs">Жирная линия — типичный пост площадки (медиана), тонкие — вузы. В сравнении вузы сопоставляются по значению через 24 часа.</p>
      </div>
    </section>
  );
}

export function Analysis({ corridor }: { corridor: ReactNode }) {
  return (
    <section aria-labelledby="landing-analysis" className="grid gap-12 py-24 sm:py-32">
      <SectionHead id="landing-analysis" eyebrow="анализ динамики" tone="var(--chart-10)" title="Коридор нормы">
        Рост каждого поста сверяется с постами того же возраста на той же площадке. Анализатор называет форму отклонения
        и её силу — это повод присмотреться, а не вывод.
      </SectionHead>
      <div className="landing-reveal">{corridor}</div>
      <aside className="landing-reveal bg-muted/40 ring-foreground/5 grid gap-3 rounded-3xl p-6 ring-1 sm:grid-cols-[auto_1fr] sm:items-center sm:gap-8 sm:p-8">
        <p className="font-heading text-lg font-bold tracking-tight">Рядом с каждым результатом —<br className="max-sm:hidden" /> объяснения, которые данные не исключают</p>
        <ul className="text-muted-foreground grid gap-2 text-sm">
          <li className="flex gap-2"><span className="text-chart-2" aria-hidden="true">—</span>пост долго показывался в рекомендациях с ровным притоком;</li>
          <li className="flex gap-2"><span className="text-chart-2" aria-hidden="true">—</span>у аккаунта крупная аудитория со сглаженным трафиком.</li>
        </ul>
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
      <div className="landing-verify-visual bg-muted/40 relative h-40 overflow-hidden rounded-2xl" aria-hidden="true">{children}</div>
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
  const className = "landing-reveal landing-verify group bg-card ring-foreground/10 focus-visible:ring-ring/60 relative flex flex-col gap-6 rounded-3xl p-5 ring-1 outline-none focus-visible:ring-2 sm:p-6";
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
    <section aria-labelledby="landing-verify" className="grid gap-12 py-24 sm:py-32">
      <SectionHead id="landing-verify" eyebrow="прозрачность" tone="var(--chart-4)" title="Проверьте всё сами">
        Код сборщиков, анализатора и сайта открыт. Любой расчёт можно повторить: тот же API отдаёт замеры, из которых
        строятся графики.
      </SectionHead>
      <div className="grid gap-4 lg:grid-cols-3">
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

