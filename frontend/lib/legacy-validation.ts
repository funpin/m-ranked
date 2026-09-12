import { first, normalizeHistoryLimit } from "./params";

/** FastAPI validates declared query values before entering the legacy handler. */
export function legacyQueryErrors(url: URL): object[] {
  const errors: object[] = [];
  const q = first(url.searchParams.getAll("q"));
  if (url.pathname === "/" && q !== undefined && [...q].length > 200) {
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
  if (url.pathname === "/compare") {
    for (const parameter of ["period", "channels", "institutions"]) {
      const values = parameter === "period" ? url.searchParams.getAll(parameter).slice(-1) : url.searchParams.getAll(parameter);
      values.forEach((raw, index) => {
        if (!/^[+-]?\d+(?:\.0+)?$/.test(raw.trim())) errors.push({ type: "int_parsing", loc: ["query", parameter, ...(parameter === "period" ? [] : [index])], msg: "Input should be a valid integer, unable to parse string as an integer", input: raw });
      });
    }
    for (const parameter of ["submitted", "include_partial"]) {
      const raw = first(url.searchParams.getAll(parameter));
      if (raw !== undefined && !["true", "false", "1", "0", "yes", "no", "on", "off", "t", "f", "y", "n"].includes(raw.toLowerCase())) errors.push({ type: "bool_parsing", loc: ["query", parameter], msg: "Input should be a valid boolean, unable to interpret input", input: raw });
    }
  }
  return errors;
}
