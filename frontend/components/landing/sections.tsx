import type { CSSProperties, ReactNode } from "react";
import { ArrowDown, ArrowRight, ArrowUpRight, BookOpen, Braces, Check, CircleSlash, X } from "lucide-react";
import Link from "@/components/native-link";
import { GithubMark } from "@/components/github-mark";
import { PlatformLogo } from "@/components/platform-logo";
import { COLLECTION_SCHEDULE, KNOWN_PLATFORMS, TRACKING_DAYS, countWithUnit, formatStat, isKnownPlatform, type SiteSummary } from "@/lib/landing";
import { REPOSITORY_URL } from "@/lib/repository";
import { cn } from "@/lib/utils";
import { BrushRibbon } from "./brush-ribbon";
import { CellNumber, SectionBar } from "./blueprint";
import { RankField } from "./rank-field";

export type LandingPlatform = { platform: string; accounts: number | null };

const brand = (platform: string) => ({ "--brand": isKnownPlatform(platform) ? `var(--platform-${platform})` : "var(--chart-2)" }) as CSSProperties;
const platformName = (platform: string) => (isKnownPlatform(platform) ? KNOWN_PLATFORMS[platform].name : platform);

/** Оглавление главной: якоря разделов и их названия для линейки справа. */
export const LANDING_SECTIONS = [
  { id: "landing-title", label: "Соцсети вузов" },
  { id: "landing-platforms", label: "Площадки" },
  { id: "how", label: "Как устроено" },
  { id: "landing-rhythm", label: "Ритм" },
  { id: "landing-analysis", label: "Анализ" },
  { id: "landing-verify", label: "Прозрачность" },
  { id: "landing-closing", label: "Одна шкала" },
] as const;

/** Заголовок раздела: крупно широким шрифтом слева, одно слово — акцентом,
 *  под ним вводный абзац, где главное выделено цветом текста. */
export function SectionHead({ title, children, id, center = false }: {
  title: ReactNode; children?: ReactNode; id?: string; center?: boolean;
}) {
  return (
    <header className={cn("grid max-w-4xl gap-6", center && "mx-auto justify-items-center text-center")}>
      <h2 id={id} className="landing-rise landing-display scroll-mt-36 text-[clamp(2.1rem,5.2vw,4.4rem)] leading-[1.02] text-balance">{title}</h2>
      {children && <p className="landing-rise text-muted-foreground max-w-2xl text-lg leading-relaxed text-pretty sm:text-xl [&_b]:text-foreground [&_b]:font-medium">{children}</p>}
    </header>
  );
}

const Accent = ({ children }: { children: ReactNode }) => <span className="landing-accent">{children}</span>;

export function Hero({ platforms }: { platforms: readonly LandingPlatform[] }) {
  return (
    <section aria-labelledby="landing-title" className="landing-band relative isolate">
      <SectionBar index={1} label="Соцсети вузов" meta="открытые данные · открытый код · сбор круглосуточно" metaStart />
      <div className="landing-bleed landing-hero-parallax pointer-events-none absolute inset-y-0 -z-10 overflow-hidden" aria-hidden="true">
        <BrushRibbon className="absolute inset-0 h-full w-full" />
        <div className="landing-hero-veil absolute inset-0" />
      </div>
      <div className="landing-hero-copy landing-pad grid min-h-[calc(100svh-7rem)] content-center gap-8 py-16">
        <p className="landing-mono inline-flex items-center gap-2.5">
          <span className="relative flex size-2" aria-hidden="true">
            <span className="bg-chart-1 absolute inline-flex size-full animate-ping rounded-full opacity-60 motion-reduce:hidden" />
            <span className="bg-chart-1 relative inline-flex size-2 rounded-full" />
          </span>
          Сбор идёт круглосуточно
        </p>
        <h1 id="landing-title" className="landing-display landing-frost w-fit text-[clamp(2.6rem,6.4vw,5.6rem)] leading-[0.98]">
          Соцсети вузов.<br /><Accent>Как есть</Accent>.
        </h1>
        <p className="text-muted-foreground max-w-xl text-lg leading-relaxed text-pretty sm:text-xl">
          Замеряем публикации официальных аккаунтов российских вузов с первых минут и показываем, как набираются
          просмотры. Код открыт.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Link href="/review" prefetch={false} data-testid="landing-cta" className="landing-button landing-button--solid group">
            Перейти к обзору
            <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
          </Link>
          <a href="#how" className="landing-button group">
            Как это устроено
            <ArrowDown className="size-4 transition-transform group-hover:translate-y-0.5" aria-hidden="true" />
          </a>
        </div>
        <ul className="mt-4 flex flex-wrap gap-6" aria-label="Площадки">
          {platforms.map(({ platform }, index) => (
            <li key={platform} className="landing-pop grid justify-items-center gap-2" style={{ "--i": index } as CSSProperties}>
              {isKnownPlatform(platform)
                ? <PlatformLogo platform={platform} size={56} decorative className="landing-app-icon" />
                : <span className="landing-app-icon bg-muted grid size-14 place-items-center text-lg font-bold">{platform.slice(0, 2).toUpperCase()}</span>}
              <span className="text-muted-foreground text-sm">{platformName(platform)}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/** Ширина числа в кеглях широкого шрифта заголовков (замер Unbounded 600):
 *  цифра ~0,65, буква ~0,62, пробел и запятая ~0,3. По ней кегль ужимается
 *  под ячейку, и число никогда не переносится на вторую строку. */
function statWidthEm(text: string) {
  let width = 0;
  for (const symbol of text) width += /\d/.test(symbol) ? 0.65 : /[\s,.]/.test(symbol) ? 0.3 : 0.62;
  return Math.round(width * 1.02 * 100) / 100;
}

/** Цифры проекта — ячейки сетки, разделённые тонкими линиями. Досчитывают при прокрутке. */
export function Stats({ summary }: { summary: SiteSummary }) {
  const items = [
    { value: summary.institutions, label: "Под наблюдением", caption: "вузов" },
    { value: summary.accounts, label: "Официальных", caption: "аккаунтов в соцсетях" },
    { value: summary.publications, label: "Публикаций", caption: "с полной историей замеров" },
    { value: summary.snapshots, label: "Около", caption: "замеров счётчиков" },
  ].filter((item): item is { value: number; label: string; caption: string } => item.value !== null);
  return (
    <section aria-label="Проект в цифрах" className="landing-band" data-testid="landing-stats">
      {/* Колонки неравные: «20,3 млн» длиннее четырёхзначных вузов и
          аккаунтов, и последней колонке отдана доля трёх первых поровну. */}
      <dl className="landing-grid landing-stats grid-cols-2">
        {items.map((item, index) => (
          <div key={item.label} className="landing-cell landing-pop landing-stat grid content-start gap-2" style={{ "--i": index } as CSSProperties}>
            <dt className="landing-mono text-muted-foreground">{item.label}</dt>
            <dd className="landing-display landing-stat-value tabular-nums" data-count={item.value}
              style={{ "--fit": statWidthEm(formatStat(item.value)) } as CSSProperties}>{formatStat(item.value)}</dd>
            <dd className="text-muted-foreground text-sm">{item.caption}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function Platforms({ platforms, phone }: { platforms: readonly LandingPlatform[]; phone: ReactNode }) {
  return (
    <section aria-labelledby="landing-platforms" className="landing-band">
      <SectionBar index={2} label="Площадки" meta="только публичные счётчики" />
      <div className="landing-pad grid gap-14 py-20 sm:py-28">
        <SectionHead id="landing-platforms" title={<>Несколько площадок. <Accent>Одна шкала</Accent>.</>}>
          У каждой площадки свои счётчики. Мы берём <b>только публичные цифры, которые видит любой читатель,</b> и
          приводим их к общему виду, чтобы вузы можно было честно сравнить.
        </SectionHead>
        {phone}
      </div>
      <ul role="list" className="landing-grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4" data-testid="landing-platforms">
        {platforms.map(({ platform, accounts }, index) => {
          const known = isKnownPlatform(platform) ? KNOWN_PLATFORMS[platform] : null;
          return (
            <li key={platform} style={{ ...brand(platform), "--i": index } as CSSProperties}
              className="landing-cell landing-slide landing-platform relative flex flex-col gap-6">
              <div className="flex items-center justify-between gap-3">
                <CellNumber value={index + 1} tone="var(--brand)" />
                <span className="landing-mono text-muted-foreground truncate">{platform === "telegram" ? "TG" : platform.toUpperCase()}</span>
              </div>
              <div className="relative w-fit">
                <span className="landing-blob" aria-hidden="true" />
                {isKnownPlatform(platform)
                  ? <PlatformLogo platform={platform} size={56} decorative className="landing-app-icon relative" />
                  : <span className="landing-app-icon bg-muted relative grid size-14 place-items-center text-lg font-bold">{platform.slice(0, 2).toUpperCase()}</span>}
              </div>
              <h3 className="landing-display text-3xl">{platformName(platform)}</h3>
              {accounts !== null && (
                <p className="landing-display text-5xl tabular-nums" style={{ color: "var(--brand)" }}>
                  {formatStat(accounts)}
                  <span className="text-muted-foreground block pt-2 font-sans text-sm font-normal tracking-normal">{countWithUnit(accounts, known?.unit ?? "аккаунт").replace(/^[\d\s\u00a0]+/, "")}</span>
                </p>
              )}
              {known && (
                <ul className="mt-auto flex flex-wrap gap-1.5" aria-label={`Счётчики ${known.name}`}>
                  {known.metrics.map((metric) => <li key={metric} className="landing-tag">{metric}</li>)}
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
      {/* Подписи в одну строку: номер суток над шагом замера, общий смысл — строкой ниже. */}
      <dl className="grid grid-cols-4 gap-1 font-mono text-[11px] leading-tight whitespace-nowrap">
        {COLLECTION_SCHEDULE.map((segment) => (
          <div key={segment.age} className="grid gap-0.5">
            <dt className="text-muted-foreground">{segment.age.replace(/^первые сутки$/, "1").replace(/\s*сутки$/, "")}</dt>
            <dd className="font-medium">{segment.step}</dd>
          </div>
        ))}
      </dl>
      <p className="text-muted-foreground text-[11px] whitespace-nowrap">сутки поста · шаг замера</p>
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
    { text: "точный замер", result: "учтён", ok: true },
    { text: "сброс счётчика", result: "исключён", ok: false },
    { text: "недостоверный", result: "исключён", ok: false },
  ];
  // Строки короткие и не переносятся: подпись слева, итог справа одной строкой.
  return (
    <ul className="grid gap-1.5 text-xs">
      {rows.map((row) => (
        <li key={row.text} className="bg-muted/50 flex items-center justify-between gap-2 rounded-lg px-2.5 py-2 whitespace-nowrap">
          <span className="min-w-0 truncate">{row.text}</span>
          <span className={cn("inline-flex shrink-0 items-center gap-1 font-medium", row.ok ? "landing-tone-text" : "text-muted-foreground")}>
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
      <div className="bg-muted/50 text-muted-foreground grid grid-cols-3 gap-x-3 px-3 py-1.5 text-[11px] uppercase">
        <span>время</span><span className="text-right">всего</span><span className="text-right">прирост</span>
      </div>
      {rows.map(([time, views, delta]) => (
        <div key={time} className="grid grid-cols-3 gap-x-3 border-t px-3 py-1.5 font-mono tabular-nums">
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
    <section aria-labelledby="how" className="landing-band">
      <SectionBar index={3} label="Как это устроено" meta="от публикации до графика" />
      <div className="landing-pad py-20 sm:py-28">
        <SectionHead id="how" title={<>От публикации <Accent>до графика</Accent>.</>}>
          Сборщики обходят аккаунты вузов по расписанию, <b>сохраняют историю каждого счётчика</b> и отправляют её на
          витрину, где из неё строятся обзор, графики и анализ.
        </SectionHead>
      </div>
      <ol role="list" className="landing-grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4">
        {STEPS.map((step, index) => (
          <li key={step.title} className="landing-cell landing-slide row-span-3 grid grid-rows-subgrid gap-6" style={{ "--i": index } as CSSProperties}>
            <div className="flex items-center justify-between">
              <CellNumber value={index + 1} />
              <span className="landing-mono text-muted-foreground">шаг</span>
            </div>
            <div className="landing-visual grid min-h-[190px] content-center p-5">{step.visual}</div>
            <p className="text-muted-foreground text-base leading-relaxed text-pretty">
              <b className="text-foreground block pb-1 text-lg font-semibold text-balance">{step.title}</b>{step.text}
            </p>
          </li>
        ))}
      </ol>
      {/* Пастельная панель: результат живыми графиками. Плитка сначала стоит с
          отступами и раскрывается на всю ширину, когда доезжает до экрана. */}
      <div className="landing-pad py-16 sm:py-20">
        <div className="landing-widen landing-panel grid gap-8 px-5 py-10 sm:px-12 sm:py-14">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <h3 className="landing-display text-[clamp(1.8rem,3.6vw,3rem)]">И вот что <Accent>получается</Accent>.</h3>
            <Link href="/compare" prefetch={false} className="landing-link group">
              Все графики — в сравнении<ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
            </Link>
          </div>
          <div className="w-full">{chart}</div>
        </div>
      </div>
    </section>
  );
}

export function Rhythm({ chart }: { chart: ReactNode }) {
  return (
    <section aria-labelledby="landing-rhythm" className="landing-band md:overflow-x-clip">
      <SectionBar index={4} label="Ритм площадок" meta="живые данные за 30 дней" />
      <div className="landing-pad grid gap-12 py-20 sm:py-28">
        <SectionHead id="landing-rhythm" title={<>Когда публикуют и <Accent>что это даёт</Accent>.</>}>
          Сколько публикаций выходит в каждый час и день недели, <b>сколько типичный пост набирает за первые сутки</b> и
          чем заканчивается проверка динамики — по живым данным за 30 дней.
        </SectionHead>
        {chart}
      </div>
    </section>
  );
}

export function Analysis({ corridor }: { corridor: ReactNode }) {
  return (
    <section aria-labelledby="landing-analysis" className="landing-band">
      <SectionBar index={5} label="Автоматический анализ" meta="наблюдение, а не обвинение" />
      <div className="landing-pad grid gap-14 py-20 sm:py-28">
        <SectionHead id="landing-analysis" title={<>Каждый пост <Accent>проверяется</Accent>.</>}>
          Пока идёт сбор, анализатор сверяет рост поста с обычным разбросом постов того же возраста на той же площадке.
          <b> Живой шум — норма:</b> сигналом становится только необычная форма роста. Её сила — повод присмотреться, а не
          вывод.
        </SectionHead>
        <div className="landing-tilt landing-panel landing-panel--soft w-full p-3 sm:p-6">{corridor}</div>
        <aside className="landing-rise grid max-w-3xl gap-3 border-l-2 pl-5" style={{ borderColor: "var(--landing-accent)" }}>
          <p className="text-xl font-semibold tracking-tight">Рядом с каждым результатом — объяснения, которые данные не исключают</p>
          <p className="text-muted-foreground text-base leading-relaxed">
            Например, пост долго показывался в рекомендациях с ровным притоком или у аккаунта крупная аудитория со
            сглаженным трафиком.
          </p>
        </aside>
      </div>
    </section>
  );
}

function VerifyCard({ href, external, tone, icon, title, text, action, children, testId, index }: {
  href: string; external?: boolean; tone: string; icon: ReactNode; title: string; text: string; action: string;
  children: ReactNode; testId: string; index: number;
}) {
  const body = (
    <>
      <div className="flex items-center justify-between">
        <span className="landing-icon-box">{icon}</span>
        <span className="landing-mono text-muted-foreground">{String(index).padStart(2, "0")}</span>
      </div>
      <div className="landing-verify-visual landing-visual relative h-40 overflow-hidden" aria-hidden="true">{children}</div>
      <div className="grid gap-2">
        <span className="landing-mono landing-tone-text">{action}</span>
        <h3 className="landing-display text-2xl">{title}</h3>
        <p className="text-muted-foreground text-base leading-relaxed">{text}</p>
      </div>
      <span className="landing-mono text-foreground mt-auto inline-flex items-center gap-1.5">
        {external ? "Открыть на GitHub" : "Читать"}
        {external
          ? <ArrowUpRight className="size-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" aria-hidden="true" />
          : <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />}
      </span>
    </>
  );
  const className = "landing-cell landing-pop landing-verify group focus-visible:ring-ring/60 relative flex flex-col gap-6 outline-none focus-visible:ring-2 focus-visible:ring-inset";
  const style = { "--brand": tone, "--tone": tone, "--i": index - 1 } as CSSProperties;
  return external
    ? <a href={href} target="_blank" rel="noopener noreferrer" className={className} style={style} data-testid={testId}>{body}</a>
    : <Link href={href} prefetch={false} className={className} style={style} data-testid={testId}>{body}</Link>;
}

export function Verify({ summary, origin }: { summary: SiteSummary | null; origin: string }) {
  const sample = summary?.available
    ? [["institutions", summary.institutions], ["accounts", summary.accounts], ["publications", summary.publications]] as const
    : [["available", false]] as const;
  return (
    <section aria-labelledby="landing-verify" className="landing-band">
      <SectionBar index={6} label="Прозрачность" meta="всё можно пересчитать" />
      <div className="landing-pad py-20 sm:py-28">
        <SectionHead id="landing-verify" title={<>Проверьте <Accent>всё сами</Accent>.</>}>
          <b>Код сборщиков, анализатора и сайта открыт.</b> Любой расчёт можно повторить: тот же API отдаёт замеры, из
          которых строятся графики.
        </SectionHead>
      </div>
      <div className="landing-grid grid-cols-1 lg:grid-cols-3">
        <VerifyCard index={1} href="/methodology" tone="var(--chart-1)" icon={<BookOpen className="size-4" />} action="Методология"
          title="Как мы считаем" text="Расписание замеров, качество данных, сравнение в одном возрасте и уровни анализа." testId="verify-methodology">
          <div className="absolute inset-5 grid content-start gap-2.5">
            {[92, 70, 84, 56, 76].map((width, index) => (
              <span key={index} className="landing-doc-line bg-foreground/10 h-2.5" style={{ width: `${width}%`, transitionDelay: `${index * 50}ms` }} />
            ))}
          </div>
          <span className="landing-doc-mark absolute top-5 left-3 h-2.5 w-1" style={{ background: "var(--chart-1)" }} />
        </VerifyCard>
        <VerifyCard index={2} href="/methodology/api" tone="var(--chart-2)" icon={<Braces className="size-4" />} action="Открытый API"
          title="Данные машинам" text="История каждого поста, обзор и сравнение — в машиночитаемом виде, без ключей." testId="verify-api">
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
        <VerifyCard index={3} href={REPOSITORY_URL} external tone="var(--chart-4)" icon={<GithubMark className="size-4" />} action="Исходный код"
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

/** Финал: одна фраза, одна кнопка и поле рейтинга за ними. */
export function Closing() {
  return (
    <section aria-labelledby="landing-closing" className="landing-band relative isolate overflow-hidden" data-testid="landing-closing">
      <SectionBar index={7} label="Одна шкала" meta="открытый код · бесплатно" />
      <div className="landing-pad grid justify-items-center gap-7 py-24 text-center sm:py-32">
        <p className="landing-mono text-muted-foreground">Открытые данные · без регистрации</p>
        <h2 id="landing-closing" className="landing-rise landing-display max-w-4xl text-[clamp(2.3rem,6vw,5rem)] leading-[1.02] text-balance">
          Сравнивайте <Accent>как вам удобно</Accent>.
        </h2>
        <p className="text-muted-foreground max-w-2xl text-lg leading-relaxed text-pretty sm:text-xl">
          Каждый вуз — на одной шкале, каждый пост — в одном возрасте. Остальное — в статистике по площадкам.
        </p>
        <Link href="/statistics" prefetch={false} className="landing-button landing-button--solid group">
          Открыть статистику<ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
        </Link>
        <RankField className="text-foreground mt-6 w-full max-w-xl" />
      </div>
    </section>
  );
}

export function LandingFooter() {
  return (
    <footer className="landing-band">
      <div className="landing-grid grid-cols-1 md:grid-cols-[minmax(0,2fr)_repeat(2,minmax(0,1fr))]">
        <div className="landing-cell grid content-start gap-4">
          <p className="landing-display text-2xl">m-ranked</p>
          <p className="text-muted-foreground max-w-sm text-base leading-relaxed">
            Открытый проект: публичные счётчики соцсетей вузов, снятые с первых минут жизни поста.
          </p>
        </div>
        <div className="landing-cell grid content-start gap-3">
          <p className="landing-mono text-muted-foreground">Данные</p>
          <p className="text-base">Telegram · ВКонтакте · MAX · Rutube</p>
        </div>
        <div className="landing-cell grid content-start gap-3">
          <p className="landing-mono text-muted-foreground">Лицензия</p>
          <p className="text-base">Код открыт, расчёты повторяемы</p>
        </div>
      </div>
      <div className="landing-bar landing-bar--end" aria-hidden="true">
        <span className="landing-mono text-muted-foreground">© {new Date().getUTCFullYear()} m-ranked</span>
        <span className="landing-mono text-muted-foreground hidden sm:block">соцсети вузов как есть</span>
      </div>
    </footer>
  );
}

export function ChartUnavailable() {
  return (
    <div className="text-muted-foreground flex h-[240px] items-center justify-center gap-2 border border-dashed text-sm">
      <X className="size-4" aria-hidden="true" />Живые графики сейчас недоступны — загляните чуть позже.
    </div>
  );
}
