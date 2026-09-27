"use client";

import * as m from "motion/react-m";

import { LandingMotion } from "./landing-motion";

/** Кривая поста, перетекающая из формы в форму (Motion). Приезжает отдельным
 *  фрагментом, когда коридор подъезжает к экрану. */
export function AnimatedCurve({ d, tone }: { d: string; tone: string }) {
  return (
    <LandingMotion>
      <m.path d={d} animate={{ d, stroke: tone }}
        initial={false} fill="none" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round"
        transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }} />
    </LandingMotion>
  );
}
