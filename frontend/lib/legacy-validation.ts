import { first, normalizeHistoryLimit } from "./params";

/** FastAPI validates declared query values before entering the legacy handler. */
export function legacyQueryErrors(url: URL): object[] {
  const errors: object[] = [];
  const q = first(url.searchParams.getAll("q"));
  if ((url.pathname === "/" || url.pathname === "/statistics") && q !== undefined && [...q].length > 200) {
    errors.push({ type: "string_too_long", loc: ["query", "q"], msg: "String should have at most 200 characters", input: q, ctx: { max_length: 200 } });
  }
  if (/^\/(posts|publications)\/[^/]+$/.test(url.pathname) && url.searchParams.has("history_limit")) {
    const raw = first(url.searchParams.getAll("history_limit"))!;
    try { normalizeHistoryLimit(raw); } catch {
      const value = Number(raw);
      const parsed = /^[+-]?\d+(?:\.0+)?$/.test(raw.trim()) && Number.isSafeInteger(value);
      if (!parsed) errors.push({ type: "int_parsing", loc: ["query", "history_limit"], msg: "Input should be a valid integer, unable to parse string as an integer", input: raw });
      else if (value < 50) errors.push({ type: "greater_than_equal", loc: ["query", "history_limit"], msg: "Input should be greater than or equal to 50", input: raw, ctx: { ge: 50 } });
      else if (value > 3000) errors.push({ type: "less_than_equal", loc: ["query", "history_limit"], msg: "Input should be less than or equal to 3000", input: raw, ctx: { le: 3000 } });
    }
  }
  // /compare больше не проверяется: прежние числовые period/channels/institutions
  // панель принимает мягко (период по умолчанию, выделение по legacy id),
  // а новый period=7d|30d число и не должен быть.
  return errors;
}
