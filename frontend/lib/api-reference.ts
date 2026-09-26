/** Справочник открытого API: русские описания к методам, которые генератор
 *  (scripts/generate-openapi.mjs) выбрал из контракта как публичные. Новый
 *  публичный метод без описания здесь не пройдёт модульный тест. */
import digest from "./api-reference.generated.json";

export type ApiParameter = {
  name: string; in: "query" | "path"; required: boolean; type: string;
  enum?: (string | number | boolean)[]; default?: string | number | boolean; minimum?: number; maximum?: number;
};
export type ApiOperation = {
  operationId: string; path: string; summary: string; parameters: ApiParameter[];
  response: string | null; fields: { name: string; type: string }[];
};

export const API_DIGEST = digest as { sourceSha256: string; version: string; operations: ApiOperation[] };

export const API_SECTIONS = [
  { id: "rating", title: "Рейтинг и статистика" },
  { id: "comparison", title: "Сравнение" },
  { id: "accounts", title: "Вузы и аккаунты" },
  { id: "publications", title: "Публикации" },
  { id: "service", title: "Сводка и ревизия" },
] as const;
type SectionId = (typeof API_SECTIONS)[number]["id"];

type OperationText = { section: SectionId; title: string; text: string; example?: string };

/** Пример в запросе: `{uuid}` и подобное подставляется вместо параметров пути. */
export const OPERATION_TEXT: Record<string, OperationText> = {
  getOverview: {
    section: "rating", title: "Рейтинг вузов",
    text: "Карточки вузов с приростом просмотров, реакций, комментариев и репостов за период и медианами по публикациям. Постранично, с курсором.",
    example: "/api/v1/overview?platform=vk&period=7d&limit=10",
  },
  getStatistics: {
    section: "rating", title: "Статистика публикаций и вузов",
    text: "Накопленные показатели публикаций (view=publications) или вузов (view=entities) за период с сортировками и поиском.",
    example: "/api/v1/statistics?platform=telegram&period=30d&limit=20",
  },
  getComparisonDashboard: {
    section: "comparison", title: "Панель сравнения",
    text: "Все вузы сразу: медианы через 24 часа, кривые накопления по часам жизни поста, публикации и доля аномалий по дням, время выхода.",
    example: "/api/v1/compare/dashboard?period=30d",
  },
  getComparison: {
    section: "comparison", title: "Сравнение выбранных вузов",
    text: "Кривые одной метрики для выбранных вузов или каналов на постоянной когорте публикаций до заданного часа.",
    example: "/api/v1/compare?platform=telegram&horizonHours=24&metric=views&aggregation=median",
  },
  getComparisonCandidates: {
    section: "comparison", title: "Кого можно сравнить",
    text: "Список вузов или каналов площадки, доступных для сравнения, с курсором.",
    example: "/api/v1/compare/candidates?platform=vk&limit=20",
  },
  getInstitution: {
    section: "accounts", title: "Вуз",
    text: "Показатели вуза на площадке за период по его числовому идентификатору.",
    example: "/api/v1/institutions/1?platform=all&period=7d",
  },
  getInstitutionAccounts: {
    section: "accounts", title: "Аккаунты вуза",
    text: "Аккаунты вуза на площадках с их показателями, постранично.",
    example: "/api/v1/institutions/1/accounts?platform=all",
  },
  getAccount: {
    section: "accounts", title: "Аккаунт",
    text: "Аккаунт площадки: название, ссылка, подписчики, состояние сбора и сводка по публикациям.",
    example: "/api/v1/accounts/{uuid}",
  },
  getAccountPublications: {
    section: "accounts", title: "Публикации аккаунта",
    text: "Публикации аккаунта с последними значениями счётчиков, постранично; можно выбрать день.",
    example: "/api/v1/accounts/{uuid}/publications?limit=20",
  },
  getAccountAnomalyLevels: {
    section: "accounts", title: "Уровни анализа по аккаунту",
    text: "Уровни анализа динамики проанализированных публикаций аккаунта.",
    example: "/api/v1/accounts/{uuid}/anomaly-levels",
  },
  getPublication: {
    section: "publications", title: "Публикация",
    text: "Публикация и последние значения её счётчиков с отметками качества.",
    example: "/api/v1/publications/{uuid}",
  },
  getPublicationHistory: {
    section: "publications", title: "История замеров",
    text: "Все замеры публикации по времени — те самые точки, из которых строится график. До 3000 за запрос, дальше — по курсору.",
    example: "/api/v1/publications/{uuid}/history?limit=3000",
  },
  getPublicationAnomalyAnalysis: {
    section: "publications", title: "Анализ динамики публикации",
    text: "Уровень, признаки с формулами и интервалами, качество данных, версии нормы и оговорка. Пост без анализа — уровень null и статус pending.",
    example: "/api/v1/publications/{uuid}/anomaly-analysis",
  },
  getSiteSummary: {
    section: "service", title: "Сводка проекта",
    text: "Число вузов, аккаунтов по площадкам, публикаций и замеров. Пересчитывается раз в сутки.",
    example: "/api/v1/site/summary",
  },
  getDatasetRevision: {
    section: "service", title: "Ревизия данных",
    text: "Номер последней опубликованной ревизии данных и её время. Ответы остальных методов несут ту же ревизию.",
    example: "/api/v1/revision",
  },
};

/** Русские описания общих параметров; остальное — по контракту. */
export const PARAMETER_TEXT: Record<string, string> = {
  platform: "Площадка; all — все сразу.",
  period: "Окно: 3 часа, сутки, 7 или 30 дней.",
  q: "Поиск по названию, до 200 символов.",
  sort: "Поле сортировки.",
  direction: "Направление сортировки.",
  limit: "Сколько записей вернуть.",
  cursor: "Курсор следующей страницы из прошлого ответа.",
  revision: "Закрепить ответ за ревизией данных.",
  legacyId: "UUID (или прежний числовой идентификатор).",
  accountId: "UUID аккаунта.",
  legacyType: "Тип прежнего числового идентификатора; для UUID не нужен.",
  view: "Публикации или вузы.",
  day: "Только публикации этого дня (ГГГГ-ММ-ДД).",
  horizonHours: "До какого часа жизни поста строить кривую.",
  includePartial: "Включать посты, ещё не дожившие до этого часа.",
  metric: "Метрика кривой.",
  aggregation: "Сумма или медиана.",
  institutionLimit: "Сколько вузов вернуть.",
  channels: "Каналы Telegram для сравнения.",
  institutions: "Вузы для сравнения.",
  selectionCursor: "Курсор выбора.",
  publication_sort: "Сортировка публикаций.",
  publication_direction: "Направление сортировки публикаций.",
  entity_sort: "Сортировка вузов.",
  entity_direction: "Направление сортировки вузов.",
};

export function operationsBySection() {
  return API_SECTIONS.map((section) => ({
    ...section,
    operations: API_DIGEST.operations
      .filter((operation) => OPERATION_TEXT[operation.operationId]?.section === section.id)
      .map((operation) => ({ ...operation, ...OPERATION_TEXT[operation.operationId]! })),
  })).filter((section) => section.operations.length > 0);
}

export function operationAnchor(operationId: string) {
  return operationId.replace(/^get/, "").replace(/[A-Z]/g, (letter, index) => `${index ? "-" : ""}${letter.toLowerCase()}`);
}
