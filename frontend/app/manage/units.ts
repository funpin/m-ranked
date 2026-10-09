/** Размеры и скорости для панели; без серверных модулей — годится и клиенту. */
export function bytes(value: number | null | undefined) {
  if (value == null) return "—";
  let unit = 0, n = value;
  while (n >= 1024 && unit < 4) { n /= 1024; unit++; }
  return `${unit ? n.toFixed(1) : Math.trunc(n)} ${["Б", "КБ", "МБ", "ГБ", "ТБ"][unit]}`;
}

export function rate(value: number | null | undefined) {
  return value == null ? "—" : `${bytes(value)}/с`;
}

export function percent(part: number | null | undefined, total: number | null | undefined, digits = 1) {
  return part != null && total ? Number((part * 100 / total).toFixed(digits)) : null;
}
