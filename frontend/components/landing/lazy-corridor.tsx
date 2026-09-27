"use client";

import { useEffect, useRef, useState, type ComponentType } from "react";
import type { CorridorModel, CorridorShapeId } from "@/lib/landing";
import { CorridorFigure, StaticCurve, toneOf } from "./corridor-figure";
import { useNear } from "./use-near";

const CYCLE_MS = 4200;

/** Коридор нормы. Выбор формы работает сразу; движок Motion для перетекания
 *  кривой грузится, только когда до блока долистали, а до того кривая
 *  меняется мгновенно. */
export function LazyCorridor({ model }: { model: CorridorModel }) {
  const [active, setActive] = useState<CorridorShapeId>("normal");
  const [touched, setTouched] = useState(false);
  const [visible, setVisible] = useState(false);
  const [Curve, setCurve] = useState<ComponentType<{ d: string; tone: string }> | null>(null);
  const figure = useRef<HTMLDivElement>(null);
  const near = useNear(figure);

  useEffect(() => {
    if (!near) return;
    let live = true;
    import("./norm-corridor").then((module) => { if (live) setCurve(() => module.AnimatedCurve); });
    return () => { live = false; };
  }, [near]);

  useEffect(() => {
    const node = figure.current;
    if (!node) return;
    const observer = new IntersectionObserver(([entry]) => setVisible(Boolean(entry?.isIntersecting)), { threshold: 0.5 });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Пока читатель не выбрал форму сам, схема перебирает их по кругу — и только
  // на экране и не для тех, кто просил меньше движения.
  useEffect(() => {
    if (touched || !visible || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => setActive((current) => {
      const index = model.shapes.findIndex((item) => item.id === current);
      return model.shapes[(index + 1) % model.shapes.length]!.id;
    }), CYCLE_MS);
    return () => window.clearInterval(timer);
  }, [touched, visible, model]);

  const shape = model.shapes.find((item) => item.id === active) ?? model.shapes[0]!;
  const tone = toneOf(shape.level);
  return (
    <CorridorFigure model={model} active={active} figureRef={figure}
      onSelect={(id) => { setTouched(true); setActive(id); }}
      curve={Curve ? <Curve d={shape.d} tone={tone} /> : <StaticCurve d={shape.d} tone={tone} />} />
  );
}
