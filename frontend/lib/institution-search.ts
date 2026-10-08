/** Поиск вуза по короткому и полному названию — общий для сравнения и
 *  «Находок». Регистр, «ё», кавычки, точки и дефисы не мешают; слова запроса
 *  ищутся в любом порядке («мгу ломоносова» → «МГУ им. М.В. Ломоносова»).
 *  Точное совпадение короткого названия выше начала слова, а то — выше
 *  совпадения в середине: «мгу» ставит МГУ раньше ОмГУ. */

export type SearchTarget = {
  shortName: string | null;
  name: string;
  /** Больше — выше среди одинаково точных совпадений (например, охват). */
  weight?: number | null;
};

export type PreparedTarget<T> = {
  item: T; short: string; words: string[]; haystack: string; weight: number;
};

const SEPARATORS = /[«»"“”„‟'‘’`´()[\]{}\-‐‑‒–—−.,;:!?/\\|_+*#№…]/g;

export function normalizeSearchText(value: string): string {
  return value.normalize("NFKC").toLocaleLowerCase("ru-RU").replaceAll("ё", "е")
    .replace(SEPARATORS, " ").replace(/\s+/g, " ").trim();
}

/** Готовит список один раз: на каждую букву запроса — только сравнение строк. */
export function prepareTargets<T>(items: readonly T[], pick: (item: T) => SearchTarget): PreparedTarget<T>[] {
  return items.map((item) => {
    const target = pick(item);
    const short = normalizeSearchText(target.shortName || target.name);
    const haystack = `${short} ${normalizeSearchText(target.name)}`;
    return { item, short, words: haystack.split(" "), haystack, weight: target.weight ?? 0 };
  });
}

function rank(target: PreparedTarget<unknown>, query: string, tokens: readonly string[]): number | null {
  if (!tokens.every((token) => target.haystack.includes(token))) return null;
  if (target.short === query) return 0;
  if (target.short.startsWith(query)) return 1;
  if (tokens.every((token) => target.words.some((word) => word.startsWith(token)))) return 2;
  return 3;
}

/** Пустой запрос — весь список в исходном порядке; при равенстве он же
 *  сохраняется (сортировка устойчива). */
export function searchInstitutions<T>(prepared: readonly PreparedTarget<T>[], query: string): T[] {
  const normalized = normalizeSearchText(query);
  if (!normalized) return prepared.map((target) => target.item);
  const tokens = normalized.split(" ");
  return prepared
    .map((target) => ({ target, rank: rank(target, normalized, tokens) }))
    .filter((match): match is { target: PreparedTarget<T>; rank: number } => match.rank !== null)
    .sort((left, right) => left.rank - right.rank || right.target.weight - left.target.weight)
    .map((match) => match.target.item);
}
