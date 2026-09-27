/** Shared translucent sticky surface. It must remain above hovered cards. */
export const STICKY_CONTROL_SURFACE_CLASS =
  "site-header-glass md:sticky md:top-[4.5rem] md:z-40 md:isolate md:shadow-lg";

/** Shared responsive geometry for the overview and statistics filter bars. */
export const FILTER_TOOLBAR_CLASS =
  `mb-5 grid grid-cols-2 items-center gap-2 rounded-xl border p-2 md:grid-cols-[max-content_max-content_minmax(0,1fr)] ${STICKY_CONTROL_SURFACE_CLASS}`;

export const FILTER_PLATFORM_CLASS = "col-span-2 row-start-1 min-w-0 md:col-span-1 md:col-start-1";
export const FILTER_PERIOD_CLASS = "col-span-2 row-start-2 min-w-0 md:col-span-1 md:col-start-2 md:row-start-1";
export const FILTER_SEARCH_CLASS = "col-span-2 row-start-3 flex min-w-0 gap-2 md:col-span-1 md:col-start-1 md:row-start-2 xl:col-start-3 xl:row-start-1";
export const FILTER_SORT_CLASS = "col-start-1 row-start-4 min-w-0 md:col-start-2 md:row-start-2 xl:col-start-1";
export const FILTER_DIRECTION_CLASS = "col-start-2 row-start-4 min-w-0 md:col-start-3 md:row-start-2 xl:col-start-2";

export const FILTER_PLATFORM_OPTIONS = [
  { value: "all", label: "Все", title: "Все соцсети" },
  { value: "telegram", label: "TG", title: "Telegram" },
  { value: "vk", label: "ВК", title: "ВКонтакте" },
  { value: "max", label: "MAX", title: "MAX" },
  { value: "rutube", label: "RT", title: "Rutube" },
] as const;

export const FILTER_PERIOD_OPTIONS = [
  { value: "3h", label: "3 ч", title: "3 часа" },
  { value: "1d", label: "Сутки", title: "Сутки" },
  { value: "7d", label: "7 дней", title: "Неделя" },
  { value: "30d", label: "30 дней", title: "Последний месяц" },
] as const;
