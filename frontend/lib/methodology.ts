/** Статьи методологии: порядок, заголовки и описания. Текст — MDX-файлы в
 *  content/methodology с теми же именами; этот список — единственное место,
 *  где статья объявляется, поэтому меню, соседние статьи и карта сайта не
 *  расходятся. */
import { REPOSITORY_URL } from "./repository";

export const ARTICLES = [
  { slug: "about", title: "Что такое m-ranked", description: "Что мы наблюдаем, что показываем и чего не утверждаем." },
  { slug: "platforms", title: "Площадки и показатели", description: "Какие счётчики отдаёт каждая площадка и почему их нельзя складывать как есть." },
  { slug: "schedule", title: "Расписание сбора", description: "Чем моложе пост, тем чаще замер: шаг сбора по возрасту и площадке." },
  { slug: "changes-and-gaps", title: "Только изменения и пробелы", description: "Почему ровный участок графика — это «не менялось», а пробел — только там, где не было сбора." },
  { slug: "data-quality", title: "Качество значений", description: "Ноль и «нет данных», сбросы счётчиков, поздно найденные посты." },
  { slug: "comparison", title: "Рейтинг и сравнение", description: "Прирост за период в рейтинге и значение в одном возрасте в сравнении." },
  { slug: "analysis", title: "Анализ динамики", description: "Признаки, нормы, уровни и альтернативные объяснения." },
  { slug: "openness", title: "Открытость и ограничения", description: "Что можно проверить самому и чего публичные счётчики не покажут." },
] as const;

export type Article = (typeof ARTICLES)[number];
export type ArticleSlug = Article["slug"];

export function articleBySlug(slug: string): Article | undefined {
  return ARTICLES.find((article) => article.slug === slug);
}

export function neighbours(slug: ArticleSlug) {
  const index = ARTICLES.findIndex((article) => article.slug === slug);
  return { previous: ARTICLES[index - 1] ?? null, next: ARTICLES[index + 1] ?? null };
}

/** Ссылка на правку статьи в репозитории. */
export function editUrl(slug: ArticleSlug) {
  return `${REPOSITORY_URL}/edit/main/frontend/content/methodology/${slug}.mdx`;
}

/** Якорь заголовка: строчные буквы любых алфавитов и цифры через дефис. Им
 *  пользуются и заголовки статьи, и оглавление — поэтому ссылки совпадают. */
export function slugify(text: string) {
  return text
    .toLocaleLowerCase("ru")
    .replace(/ё/g, "е")
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "");
}

export type TocEntry = { id: string; text: string; level: 2 | 3 };

/** Заголовки второго и третьего уровня из исходника статьи — для оглавления.
 *  Блоки кода пропускаются: строка «## » в примере не заголовок. */
export function headingsOf(source: string): TocEntry[] {
  const entries: TocEntry[] = [];
  let fenced = false;
  for (const line of source.split("\n")) {
    if (/^\s*```/.test(line)) fenced = !fenced;
    const match = fenced ? null : /^(#{2,3})\s+(.+?)\s*#*\s*$/.exec(line);
    if (!match) continue;
    const text = match[2]!.replace(/[*_`]/g, "").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
    entries.push({ id: slugify(text), text, level: match[1]!.length as 2 | 3 });
  }
  return entries;
}
