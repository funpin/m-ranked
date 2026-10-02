import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { BUNDLED_CONTRIBUTORS, isContributor } from "../lib/contributor";
import { readContributors, resetContributorsCache } from "../lib/contributors.server";

const fresh = [
  { login: "akk0sfx", contributions: 150, url: "https://github.com/akk0sfx", avatar: "/contributors/live/akk0sfx-0123456789ab.png" },
  { login: "funpin", contributions: 80, url: "https://github.com/funpin", avatar: "/contributors/live/funpin-ba9876543210.jpg" },
];

test("server listing replaces the bundled one and is cached", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "contributors-"));
  await writeFile(path.join(directory, "contributors.json"), JSON.stringify(fresh));
  process.env.MRANKED_CONTRIBUTORS_DIR = directory;
  resetContributorsCache();
  assert.deepEqual(await readContributors(1_000), fresh);
  await writeFile(path.join(directory, "contributors.json"), "[]");
  assert.deepEqual(await readContributors(2_000), fresh, "кэш на десять минут");
  resetContributorsCache();
  assert.deepEqual(await readContributors(3_000), BUNDLED_CONTRIBUTORS, "пустой список не принимается");
});

test("foreign links and paths in the file are rejected", () => {
  assert.equal(isContributor({ ...fresh[0], url: "https://evil.test/akk0sfx" }), false);
  assert.equal(isContributor({ ...fresh[0], avatar: "/contributors/live/../../etc/passwd.png" }), false);
  assert.equal(isContributor({ ...fresh[0], avatar: "https://avatars.githubusercontent.com/u/1" }), false);
  assert.ok(BUNDLED_CONTRIBUTORS.every(isContributor));
});

test("without a directory the bundled listing is used", async () => {
  delete process.env.MRANKED_CONTRIBUTORS_DIR;
  resetContributorsCache();
  assert.deepEqual(await readContributors(), BUNDLED_CONTRIBUTORS);
});
