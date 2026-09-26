// Контрибуторы репозитория для шапки сайта. Список и аватары кладутся в сам
// сайт (lib/contributors.generated.json, public/contributors/): посетители не
// ходят на GitHub, а сборка не зависит от его доступности.
// Запуск: pnpm generate:contributors — после заметных изменений состава.
import { mkdir, readdir, rm, writeFile } from "node:fs/promises";

const REPOSITORY = "funpin/m-ranked";
const LIMIT = 8;
const headers = { accept: "application/vnd.github+json", "user-agent": "m-ranked-contributors" };
const response = await fetch(`https://api.github.com/repos/${REPOSITORY}/contributors?per_page=${LIMIT * 2}`, { headers });
if (!response.ok) throw new Error(`GitHub ответил ${response.status}`);
const people = (await response.json()).filter((person) => person.type === "User").slice(0, LIMIT);

const directory = new URL("../public/contributors/", import.meta.url);
await rm(directory, { recursive: true, force: true });
await mkdir(directory, { recursive: true });
const contributors = [];
for (const person of people) {
  const avatar = await fetch(`${person.avatar_url}${person.avatar_url.includes("?") ? "&" : "?"}s=64`, { headers });
  if (!avatar.ok) throw new Error(`аватар ${person.login}: ${avatar.status}`);
  const extension = (avatar.headers.get("content-type") ?? "").includes("png") ? "png" : "jpg";
  await writeFile(new URL(`${person.login}.${extension}`, directory), Buffer.from(await avatar.arrayBuffer()));
  contributors.push({ login: person.login, contributions: person.contributions, url: person.html_url, avatar: `/contributors/${person.login}.${extension}` });
}
await writeFile(new URL("../lib/contributors.generated.json", import.meta.url), `${JSON.stringify(contributors, null, 2)}\n`);
console.log(`контрибуторов: ${contributors.length}; файлов: ${(await readdir(directory)).length}`);
