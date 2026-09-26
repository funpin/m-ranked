"use client";

import { LazyMotion, MotionConfig } from "motion/react";
import type { ReactNode } from "react";

const features = () => import("./motion-features").then((module) => module.default);

/** Motion для анимированных блоков главной. Кто просил меньше движения, получает
 *  мгновенные переходы: reducedMotion="user" отключает трансформации. */
export function LandingMotion({ children }: { children: ReactNode }) {
  return (
    <LazyMotion features={features} strict>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </LazyMotion>
  );
}
