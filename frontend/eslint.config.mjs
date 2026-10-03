import { fixupConfigRules } from "@eslint/compat";
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default defineConfig([
  ...fixupConfigRules(nextVitals),
  ...fixupConfigRules(nextTypescript),
  globalIgnores([".next/**", ".next-*/**", "evidence/**", "test-results/**", "playwright-report/**"]),
  // Компоненты animate-ui вендорятся из их реестра как есть (shadcn add):
  // правила React Compiler, которым их код не следует, отключены только здесь,
  // чтобы обновление из реестра не превращалось в ручную правку.
  {
    files: ["components/animate-ui/**", "hooks/use-auto-height.tsx", "hooks/use-controlled-state.tsx"],
    rules: {
      "react-hooks/immutability": "off",
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/static-components": "off",
      "react-hooks/refs": "off",
    },
  },
]);
