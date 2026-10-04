/**
 * Opaque sticky control surface. Stuck, it hangs from the header's bottom rule
 * with no gap (useStuck sets data-stuck). z-40 keeps it above hovered cards and
 * below z-50 popups, including menus that open from the header.
 */
export const STICKY_CONTROL_SURFACE_CLASS = [
  "bg-card text-card-foreground rounded-xl border",
  "shadow-[0_1px_2px_rgb(0_0_0/0.04),0_12px_32px_-20px_rgb(0_0_0/0.28)]",
  "dark:shadow-[inset_0_1px_0_rgb(255_255_255/0.05),0_16px_40px_-22px_rgb(0_0_0/0.9)]",
  "transition-[border-radius,border-color,box-shadow] duration-300 ease-out motion-reduce:transition-none",
  "md:sticky md:top-14 md:z-40 md:isolate",
  "md:data-stuck:rounded-t-none md:data-stuck:border-t-transparent",
  "md:data-stuck:shadow-[0_24px_48px_-28px_rgb(0_0_0/0.4)]",
  "dark:md:data-stuck:shadow-[inset_0_-1px_0_rgb(255_255_255/0.04),0_24px_48px_-24px_rgb(0_0_0/0.95)]",
].join(" ");

/** Six-column phone/tablet grid shared by every public filter bar. */
export const FILTER_GRID_CLASS = "mb-6 grid grid-cols-6 items-center gap-2 p-2.5";

/** Shared responsive geometry for the overview filter bar. */
export const FILTER_TOOLBAR_CLASS =
  `${FILTER_GRID_CLASS} xl:grid-cols-[240px_210px_80px_minmax(180px,220px)_minmax(180px,1fr)] ${STICKY_CONTROL_SURFACE_CLASS}`;

/** Filter selects keep the toolbar's 32px row instead of the preset's 28px. */
export const FILTER_SELECT_CLASS = "w-full [&>select]:h-8 [&>select]:pl-2.5 [&>select]:pr-8 [&>select]:text-sm [&>svg]:right-2.5 [&>svg]:size-4";

export const FILTER_PLATFORM_CLASS = "col-span-6 row-start-1 min-w-0 sm:col-span-3 xl:col-span-1 xl:col-start-1";
export const FILTER_PERIOD_CLASS = "col-span-4 row-start-2 min-w-0 sm:col-span-3 sm:col-start-4 sm:row-start-1 xl:col-span-1 xl:col-start-2";
export const FILTER_DIRECTION_CLASS = "col-span-2 col-start-5 row-start-2 min-w-0 sm:col-span-1 sm:col-start-1 xl:col-start-3 xl:row-start-1";
export const FILTER_SORT_CLASS = "col-span-6 row-start-3 min-w-0 sm:col-span-2 sm:col-start-2 sm:row-start-2 xl:col-span-1 xl:col-start-4 xl:row-start-1";
export const FILTER_SEARCH_CLASS = "col-span-6 row-start-4 min-w-0 sm:col-span-3 sm:col-start-4 sm:row-start-2 xl:col-span-1 xl:col-start-5 xl:row-start-1";

export const FILTER_PLATFORM_OPTIONS = [
  { value: "all", label: "Все", title: "Все соцсети" },
  { value: "telegram", label: "TG", title: "Telegram" },
  { value: "vk", label: "ВК", title: "ВКонтакте" },
  { value: "max", label: "MAX", title: "MAX" },
  { value: "rutube", label: "RT", title: "Rutube" },
] as const;

export const FILTER_PERIOD_OPTIONS = [
  { value: "3h", label: "3 ч", title: "3 часа" },
  { value: "1d", label: "24 ч", title: "Сутки" },
  { value: "7d", label: "7 д", title: "Неделя" },
  { value: "30d", label: "30 д", title: "Последний месяц" },
] as const;
