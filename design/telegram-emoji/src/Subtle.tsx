import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { LOOP } from "./brand";

// Еле заметное движение для «спокойных» значков (решение владельца: анимация у
// всех, но у второстепенных — так, чтобы не раздражала). Всё — по синусу на
// полный цикл LOOP, поэтому первый и последний кадр совпадают и повтор бесшовный.

const wave = (frame: number, shift = 0) => Math.sin(((frame / LOOP) + shift) * Math.PI * 2);

// Плавное «дыхание»: подъём на ~1.5 px и масштаб до 1.5 %. Форма и цвет не
// меняются — годится и для официальных знаков площадок.
export const Breathe: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const frame = useCurrentFrame();
  const w = wave(frame);
  return (
    <AbsoluteFill style={{ transform: `translateY(${-1.5 * (w + 1) / 2}px) scale(${1 + 0.015 * (w + 1) / 2})` }}>
      {children}
    </AbsoluteFill>
  );
};

// Сдвиг на 2 px по направлению (стрелки роста и падения) и обратно.
export const Nudge: React.FC<{ dy: number; children: React.ReactNode }> = ({ dy, children }) => {
  const frame = useCurrentFrame();
  const w = (wave(frame) + 1) / 2;
  return <AbsoluteFill style={{ transform: `translateY(${dy * w}px)` }}>{children}</AbsoluteFill>;
};

// Покачивание на ±3° (рупор «продвижения»).
export const Sway: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{ transform: `rotate(${3 * wave(frame)}deg)` }}>{children}</AbsoluteFill>;
};

// Яркость ±3 % — для плашек: пять эмодзи подряд Telegram может запускать не
// одновременно, а такое изменение рассинхрона не выдаёт.
export const Glow: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{ filter: `brightness(${1 + 0.03 * wave(frame)})` }}>{children}</AbsoluteFill>;
};

// Слабый блик, раз за цикл проходящий по диагонали (медали мест).
export const Glint: React.FC<{ children: React.ReactNode; radius: number }> = ({ children, radius }) => {
  const frame = useCurrentFrame();
  const t = frame / LOOP;
  const x = -60 + 220 * Math.min(1, Math.max(0, (t - 0.55) / 0.3));
  return (
    <AbsoluteFill>
      {children}
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ width: 88, height: 88, borderRadius: radius, overflow: "hidden", position: "relative" }}>
          <div style={{ position: "absolute", top: -20, left: x, width: 18, height: 130, transform: "rotate(25deg)",
                        background: "rgba(255,255,255,0.32)", filter: "blur(4px)" }} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
