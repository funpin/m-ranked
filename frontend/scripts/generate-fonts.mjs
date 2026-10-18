// Собирает app/fonts/fonts.ts и app/fonts/fallbacks.css из app/fonts/faces.json.
//
// Шрифты сайта лежат в репозитории (app/fonts/*.woff2), а не скачиваются с
// Google Fonts при каждой сборке: 18.10.2026 сборка в CI упала, когда Google
// не отдал файлы. Файлы — ровно те, что next/font/google нарезал в рабочей
// сборке (кириллица, латиница и прочие наборы отдельно, с unicode-range), так
// что браузер грузит те же байты, что и раньше.
//
// next/font/local не знает наборов символов, поэтому каждый набор — отдельный
// вызов с unicode-range в declarations. Каждый вызов даёт своё семейство;
// переменная (--font-heading и др.) перечисляет их все, а браузер для каждого
// символа берёт первое семейство, чей диапазон его покрывает. В одном
// семействе из нескольких @font-face при пересечении диапазонов выигрывает
// объявленное последним, поэтому наборы идут в обратном порядке: иначе на
// главной вместо «символов» Onest (18 КБ) грузились бы «математика» (25 КБ).
// Запасной шрифт с метриками — один на
// семейство (fallbacks.css), автоматические запасные выключены: иначе Arial
// встал бы в список сразу после первого набора и перехватил бы остальные.
//
//   node scripts/generate-fonts.mjs
import { readFileSync, writeFileSync } from "node:fs";

const root = new URL("../app/fonts/", import.meta.url);
const { faces, fallbacks } = JSON.parse(readFileSync(new URL("faces.json", root), "utf8"));

// Семейство → переменная CSS и где подключается (Unbounded — только главная).
const FAMILIES = {
  Geologica: { variable: "--font-heading", module: "layout" },
  Onest: { variable: "--font-sans", module: "layout" },
  "JetBrains Mono": { variable: "--font-mono", module: "layout" },
  Unbounded: { variable: "--font-display", module: "landing" },
};
// Веса вариативных файлов; у Unbounded страница берёт 500 и 600 из одного файла.
const WEIGHTS = { Geologica: "100 900", Onest: "100 900", "JetBrains Mono": "100 800", Unbounded: "500 600" };

const camel = (text) => text.toLowerCase().replace(/[^a-z0-9]+(.)/g, (_, c) => c.toUpperCase());

function moduleSource(module) {
  const lines = [
    "// Сгенерировано scripts/generate-fonts.mjs из app/fonts/faces.json — не править руками.",
    'import localFont from "next/font/local";',
    "",
  ];
  const exports = [];
  for (const [family, { variable, module: where }] of Object.entries(FAMILIES)) {
    if (where !== module) continue;
    const names = [];
    for (const face of faces.filter((item) => item.family === family).reverse()) {
      const subset = face.file.replace(/\.woff2$/, "").slice(family.length + 1);
      const name = camel(`${family} ${subset}`);
      names.push(name);
      lines.push(
        `const ${name} = localFont({`,
        `  src: "./${face.file}",`,
        `  weight: "${WEIGHTS[family]}",`,
        '  display: "swap",',
        `  preload: ${face.preload},`,
        "  adjustFontFallback: false,",
        `  declarations: [{ prop: "unicode-range", value: "${face.range}" }],`,
        "});",
      );
    }
    const constant = camel(`${family} stack`);
    lines.push(
      `// ${family}: наборы символов по порядку, затем запасной с метриками (fallbacks.css).`,
      `const ${constant} = [${names.join(", ")}].map((font) => font.style.fontFamily)`,
      `  .concat('"${family} Fallback"').join(", ");`,
      "",
    );
    exports.push(`  "${variable}": ${constant},`);
  }
  lines.push(
    "/** Переменные шрифтов для style корневого элемента. */",
    `export const ${module === "layout" ? "fontVariables" : "landingFontVariables"} = {`,
    ...exports,
    "} as Record<string, string>;",
    "",
  );
  return lines.join("\n");
}

writeFileSync(new URL("fonts.ts", root), moduleSource("layout"));
writeFileSync(new URL("landing-fonts.ts", root), moduleSource("landing"));

const css = ["/* Сгенерировано scripts/generate-fonts.mjs: запасные шрифты с метриками, как у next/font/google. */"];
for (const [family, metrics] of Object.entries(fallbacks)) {
  css.push(`@font-face {`, `  font-family: "${family} Fallback";`, "  src: local(Arial);",
    ...Object.entries(metrics).map(([prop, value]) => `  ${prop}: ${value};`), "}");
}
writeFileSync(new URL("fallbacks.css", root), css.join("\n") + "\n");
console.log(`fonts.ts, landing-fonts.ts, fallbacks.css: ${faces.length} наборов`);
