export type DaySelectionMode = "median" | "total";

/** Builds the same page URL with an optional day and its chart interpretation. */
export function selectedDayHref(pathname: string, search: string, day?: string, mode?: DaySelectionMode) {
  const params = new URLSearchParams(search);
  if (day) {
    params.set("day", day);
    params.set("trend", mode ?? "median");
  } else {
    params.delete("day");
    params.delete("trend");
  }
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}
