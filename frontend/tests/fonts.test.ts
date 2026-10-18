import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const frontend = new URL("..", import.meta.url).pathname;
const fonts = join(frontend, "app", "fonts");

function sources(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (name === "node_modules" || name.startsWith(".")) return [];
    return statSync(path).isDirectory() ? sources(path) : /\.(tsx?|mts|css)$/.test(name) ? [path] : [];
  });
}

test("сборка не ходит в Google Fonts: next/font/google нигде не подключён", () => {
  const offenders = ["app", "components", "lib"].flatMap((dir) => sources(join(frontend, dir)))
    .filter((path) => /from\s+["']next\/font\/google["']|fonts\.googleapis\.com/.test(readFileSync(path, "utf8")));
  assert.deepEqual(offenders, []);
});

test("каждый набор из faces.json лежит в репозитории", () => {
  const { faces } = JSON.parse(readFileSync(join(fonts, "faces.json"), "utf8")) as { faces: { file: string }[] };
  assert.equal(faces.length, 24);
  for (const face of faces) assert.ok(existsSync(join(fonts, face.file)), face.file);
});

test("fonts.ts, landing-fonts.ts и fallbacks.css совпадают с выводом генератора", () => {
  const before = ["fonts.ts", "landing-fonts.ts", "fallbacks.css"].map((name) => readFileSync(join(fonts, name), "utf8"));
  execFileSync(process.execPath, [join(frontend, "scripts", "generate-fonts.mjs")], { stdio: "ignore" });
  const after = ["fonts.ts", "landing-fonts.ts", "fallbacks.css"].map((name) => readFileSync(join(fonts, name), "utf8"));
  assert.deepEqual(after, before, "запустите node scripts/generate-fonts.mjs и закоммитьте результат");
});
