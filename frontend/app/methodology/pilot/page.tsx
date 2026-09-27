import type { Metadata } from "next";
import { ArrowLeft, ArrowUpRight, FlaskConical } from "lucide-react";
import Link from "@/components/native-link";

export const metadata: Metadata = {
  title: "Пробный расчёт M1/M2",
  description: "Результат исследовательского расчёта на локальной архивной копии MAX, ограничения данных и следующий шаг.",
  alternates: { canonical: "/methodology/pilot" },
};

const cases = [
  {
    id: "e57b99d9-5628-5ff9-bc92-ee5ab8b5b778",
    title: "Контекст ослабил редкость",
    growth: "+9 просмотров за 40 минут",
    context: "Новый пост: 7 позиций дальше, 104 просмотра",
    m1: "0,0592",
    m2: "0,1538",
  },
  {
    id: "858b8cd9-c3e7-53a9-8a18-6ab04d79ba9b",
    title: "Контекст усилил редкость",
    growth: "+27 просмотров за 5 минут",
    context: "Новый пост: 2 позиции дальше, 86 просмотров",
    m1: "0,8611",
    m2: "0,0400",
  },
] as const;

export default function M2PilotPage() {
  return (
    <article className="grid max-w-5xl gap-10 pb-12">
      <header className="grid gap-4">
        <Link href="/methodology" prefetch={false}
          className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-2 text-sm transition-colors">
          <ArrowLeft aria-hidden="true" className="size-4" /> Методология
        </Link>
        <div className="text-chart-2 inline-flex w-fit items-center gap-2 text-sm font-semibold">
          <FlaskConical aria-hidden="true" className="size-4" /> Исследовательский расчёт
        </div>
        <h1 className="font-heading text-4xl leading-tight font-bold tracking-tight sm:text-5xl">M1/M2 на реальных измерениях</h1>
        <p className="text-muted-foreground max-w-3xl text-base leading-relaxed sm:text-lg">
          Локальная архивная копия на 23 сентября 2026 года. Это проверка метода на данных MAX,
          а не оценка искусственной активности и не новый публичный статус.
        </p>
      </header>

      <section aria-labelledby="pilot-data" className="grid gap-5">
        <h2 id="pilot-data" className="font-heading text-2xl font-bold tracking-tight">Что проверили</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="bg-card ring-foreground/10 grid gap-1 rounded-2xl p-5 ring-1">
            <strong className="font-heading text-3xl tabular-nums">632</strong>
            <span className="text-muted-foreground text-sm">поста из 79 аккаунтов MAX</span>
          </div>
          <div className="bg-card ring-foreground/10 grid gap-1 rounded-2xl p-5 ring-1">
            <strong className="font-heading text-3xl tabular-nums">1 507</strong>
            <span className="text-muted-foreground text-sm">сопоставимых окон с новым постом</span>
          </div>
          <div className="bg-card ring-foreground/10 grid gap-1 rounded-2xl p-5 ring-1">
            <strong className="font-heading text-3xl tabular-nums">0</strong>
            <span className="text-muted-foreground text-sm">общих постов между обучением и проверкой</span>
          </div>
        </div>
        <p className="text-muted-foreground max-w-3xl text-sm leading-relaxed">
          M1 учитывает возраст поста, длительность замера и аккаунт. M2 дополнительно сравнивает
          окна по позиции нового поста и его измеренному охвату. Обучение: 7–13 сентября,
          калибровка: 14–18, контроль: 19–23.
        </p>
      </section>

      <section aria-labelledby="pilot-result" className="grid gap-4">
        <h2 id="pilot-result" className="font-heading text-2xl font-bold tracking-tight">Что получилось</h2>
        <div className="bg-card ring-foreground/10 overflow-hidden rounded-2xl ring-1">
          <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3 border-b p-4 text-sm font-semibold sm:gap-6 sm:px-6">
            <span>Ранг ≤ 0,05 в одних и тех же окнах</span><span>M1</span><span>M2</span>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3 p-4 text-sm sm:gap-6 sm:px-6">
            <span>Интервалы с новым постом</span><strong className="tabular-nums">12</strong><strong className="tabular-nums">52</strong>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3 border-t p-4 text-sm sm:gap-6 sm:px-6">
            <span>Разные посты среди них</span><strong className="tabular-nums">8</strong><strong className="tabular-nums">31</strong>
          </div>
        </div>
        <p className="max-w-3xl text-sm leading-relaxed">
          В этой архивной проверке M2 <strong>не снизил число малых рангов</strong>. Поэтому
          метод пока не добавлен в публичную оценку. Ранг показывает редкость относительно
          выбранной группы, а не вероятность накрутки.
        </p>
      </section>

      <section aria-labelledby="pilot-examples" className="grid gap-4">
        <h2 id="pilot-examples" className="font-heading text-2xl font-bold tracking-tight">Два окна из проверки</h2>
        <div className="grid gap-3 md:grid-cols-2">
          {cases.map((item) => (
            <div key={item.id} className="bg-card ring-foreground/10 grid gap-3 rounded-2xl p-5 ring-1">
              <h3 className="font-heading text-lg font-bold">{item.title}</h3>
              <p className="text-sm">{item.growth}</p>
              <p className="text-muted-foreground text-sm">{item.context}</p>
              <p className="text-sm tabular-nums">Ранг M1 <strong>{item.m1}</strong> → M2 <strong>{item.m2}</strong></p>
              <Link href={`/publications/${item.id}`} prefetch={false}
                className="text-chart-2 inline-flex w-fit items-center gap-1 text-sm font-medium hover:underline">
                Исходный пост <ArrowUpRight aria-hidden="true" className="size-4" />
              </Link>
            </div>
          ))}
        </div>
      </section>

      <aside className="bg-muted/40 ring-foreground/10 grid gap-2 rounded-2xl p-5 text-sm leading-relaxed ring-1">
        <strong>Ограничение архива</strong>
        <p className="text-muted-foreground">
          Сохранены в основном изменения счётчиков: неизменившиеся успешные опросы отсутствуют.
          Порядок ленты восстановлен из видимых сейчас постов, переходы между ними не измерены.
          Для следующего шага нужны полные будущие замеры, отдельная модель округления Telegram,
          поздних рекомендаций VK и проверка ошибок на независимой разметке.
        </p>
      </aside>
    </article>
  );
}
