import assert from "node:assert/strict";
import test from "node:test";
import { first, normalizePlatform } from "../lib/params";
import { legacyQueryErrors } from "../lib/legacy-validation";
import { publicOrigin } from "../lib/deployment";

test("scalar query values select last occurrence just like Starlette", () => {
  assert.equal(first(["a", "b"]), "b");
  assert.equal(normalizePlatform(["vk", "max"]), "max");
  assert.equal(normalizePlatform(["vk", "invalid"]), "telegram");
  assert.equal(legacyQueryErrors(new URL(`https://test/?q=${"a".repeat(201)}&q=valid`)).length, 0);
});

test("oversized q validates before trim and uses unicode codepoint length", () => {
  assert.equal(legacyQueryErrors(new URL(`https://test/?q=${"a".repeat(201)}`)).length, 1);
  assert.equal(legacyQueryErrors(new URL(`https://test/?q=${"😀".repeat(200)}`)).length, 0);
  assert.equal(legacyQueryErrors(new URL(`https://test/?q=${"%20".repeat(201)}`)).length, 1);
});

test("history_limit rejects invalid syntax and bounds rather than substituting defaults", () => {
  for (const value of ["bad", "1e2", "0x64", "49", "1001", ""]) assert.equal(legacyQueryErrors(new URL(`https://test/posts/1?history_limit=${value}`)).length, 1, value);
  for (const value of ["50", "100.0", "1000"]) assert.equal(legacyQueryErrors(new URL(`https://test/posts/1?history_limit=${value}`)).length, 0, value);
});

test("metadata uses the production origin and rejects ambiguous deployment configuration", () => {
  assert.equal(publicOrigin().origin, "https://m.funpin.org");
  for (const value of ["http://example.test", "https://user:pass@example.test", "https://example.test/path", "https://example.test/?x=1"]) assert.throws(() => publicOrigin(value));
});
