"use client";

import type { ReactNode } from "react";
import { LazyMotion, MotionConfig } from "motion/react";

const loadFeatures = () => import("./motion-features-max").then((module) => module.default);

/**
 * Анимации всего сайта (компоненты animate-ui) работают на лёгких m-компонентах:
 * в первой загрузке страницы — только их ядро, а движок догружается сам.
 * Пользователь, попросивший систему уменьшить движение, анимаций не видит.
 */
export function MotionProvider({ children }: { children: ReactNode }) {
  return (
    <LazyMotion features={loadFeatures}>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </LazyMotion>
  );
}
