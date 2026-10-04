import { FILTER_GRID_CLASS, STICKY_CONTROL_SURFACE_CLASS } from "@/components/filter-toolbar";

// Геометрия живёт рядом со страницей, а не в общем filter-toolbar: тот
// подключают заготовки загрузки всех страниц, и строки классов «Находок»
// иначе ехали бы в каждый бандл.
/**
 * Findings bar: the same surface, grid and 32px controls, plus a mode switch
 * and the «Фильтры» popover. Rows always fill the grid: phone 6 / 6 / 4+2 /
 * 4+2 / 6, tablet 2+4 / 2+1+3 / 2+4, lg 2+2+1+1 / 2+1+3, xl one row. The
 * institution field of «Мой вуз» takes a full row: after the mode on phones,
 * after mode and platform on tablets, last from lg up.
 */
export const FINDINGS_TOOLBAR_CLASS =
  `${FILTER_GRID_CLASS} xl:grid-cols-[180px_240px_150px_80px_minmax(160px,224px)_auto_minmax(180px,1fr)] ${STICKY_CONTROL_SURFACE_CLASS}`;
export const FINDINGS_MODE_CLASS = "col-span-6 min-w-0 sm:col-span-2 xl:col-span-1";
export const FINDINGS_INSTITUTION_CLASS = "col-span-6 min-w-0 sm:order-1 lg:order-last xl:col-span-full";
export const FINDINGS_PLATFORM_CLASS = "col-span-6 min-w-0 sm:col-span-4 lg:col-span-2 xl:col-span-1";
export const FINDINGS_PERIOD_CLASS = "col-span-4 min-w-0 sm:order-2 sm:col-span-2 lg:order-none lg:col-span-1";
export const FINDINGS_DIRECTION_CLASS = "col-span-2 min-w-0 sm:order-2 sm:col-span-1 lg:order-none";
export const FINDINGS_SORT_CLASS = "col-span-4 min-w-0 sm:order-2 sm:col-span-3 lg:order-none lg:col-span-2 xl:col-span-1";
export const FINDINGS_FILTERS_CLASS = "col-span-2 min-w-0 sm:order-2 lg:order-none lg:col-span-1";
export const FINDINGS_SEARCH_CLASS = "col-span-6 min-w-0 sm:order-2 sm:col-span-4 lg:order-none lg:col-span-3 xl:col-span-1";
