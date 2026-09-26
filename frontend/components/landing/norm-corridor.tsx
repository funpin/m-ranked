"use client";

import * as m from "motion/react-m";
import type { CorridorShapeId } from "@/lib/landing";
import { CORRIDOR_PATHS, LEVEL_TONES, shapeOf } from "./corridor-figure";
import { LandingMotion } from "./landing-motion";

/** Кривая поста, перетекающая из формы в форму (Motion). Приезжает отдельным
 *  фрагментом, когда коридор подъезжает к экрану. */
export function AnimatedCurve({ id }: { id: CorridorShapeId }) {
  return (
    <LandingMotion>
      <m.path d={CORRIDOR_PATHS[id]} animate={{ d: CORRIDOR_PATHS[id], stroke: LEVEL_TONES[shapeOf(id).level] }}
        initial={false} fill="none" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round"
        transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }} />
    </LandingMotion>
  );
}
