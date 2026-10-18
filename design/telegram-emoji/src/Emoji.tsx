import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { C, LOGO_PATHS, LOOP } from "./brand";
import { Breathe, Glint, Nudge, Sway } from "./Subtle";

// Все эмодзи — 100×100 на прозрачном фоне: Telegram показывает их и на
// светлой, и на тёмной теме, поэтому у каждого значка своя «плитка».

const Tile: React.FC<{ bg: string; children: React.ReactNode; radius?: number }> = ({ bg, children, radius = 24 }) => (
  <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
    <div style={{ width: 92, height: 92, borderRadius: radius, background: bg, position: "relative", overflow: "hidden",
                  display: "flex", alignItems: "center", justifyContent: "center" }}>
      {children}
    </div>
  </AbsoluteFill>
);

// --- логотип (анимированный): столбики «дышат», как rank-grow на сайте --------

export const Logo: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  // Каждый столбик проседает и пружинит обратно со сдвигом; к концу цикла —
  // исходное положение, поэтому повтор бесшовный.
  const lift = (delay: number) => {
    const down = spring({ frame: frame - delay, fps, config: { damping: 14, stiffness: 120 }, durationInFrames: 18 });
    const up = spring({ frame: frame - delay - 14, fps, config: { damping: 9, stiffness: 140 }, durationInFrames: 30 });
    return 1 - 0.34 * down + 0.34 * up;
  };
  const scales = [lift(4), lift(10), lift(16)];
  return (
    <Tile bg={C.ink}>
      <svg viewBox="-40 -150 669 644" width={84} height={84}>
        {LOGO_PATHS.map((path, index) => (
          <g key={index} style={{ transformBox: "fill-box", transformOrigin: "50% 100%",
                                   transform: `scaleY(${scales[index]})` }}>
            <path d={path.d} fill={path.fill} />
          </g>
        ))}
      </svg>
    </Tile>
  );
};

// --- площадки (неподвижные): официальные знаки без изменений -------------------

export const Platform: React.FC<{ file: string }> = ({ file }) => (
  <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
    <Img src={staticFile(file)} style={{ width: 86, height: 86 }} />
  </AbsoluteFill>
);

// --- места 1–2–3 -----------------------------------------------------------------

export const Rank: React.FC<{ place: 1 | 2 | 3 }> = ({ place }) => {
  const color = { 1: C.gold, 2: C.silver, 3: C.bronze }[place];
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: 88, height: 88, borderRadius: 44, background: color,
                    boxShadow: "inset 0 -6px 0 rgba(0,0,0,0.18)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontFamily: "Geologica", fontWeight: 800, fontSize: 56, color: C.ink, lineHeight: 1 }}>
        {place}
      </div>
    </AbsoluteFill>
  );
};

// --- рост и падение ---------------------------------------------------------------

export const Trend: React.FC<{ dir: "up" | "down" }> = ({ dir }) => {
  const color = dir === "up" ? C.up : C.down;
  return (
    <Tile bg={`${color}2e`}>
      <svg viewBox="0 0 100 100" width={70} height={70} style={{ transform: dir === "down" ? "scaleY(-1)" : undefined }}>
        <path d="M50 14 L86 56 H62 V86 H38 V56 H14 Z" fill={color} stroke={color} strokeWidth={6} strokeLinejoin="round" />
      </svg>
    </Tile>
  );
};

// --- продвижение (неподвижный рупор) ---------------------------------------------

export const Promo: React.FC = () => (
  <Tile bg={C.amber}>
    <svg viewBox="0 0 100 100" width={72} height={72}>
      <path d="M18 42 h14 l34 -18 v52 l-34 -18 h-14 z" fill={C.white} strokeLinejoin="round" stroke={C.white} strokeWidth={5} />
      <path d="M34 60 l6 22 h10 l-5 -20" fill={C.white} />
      <path d="M76 38 q10 12 0 24" stroke={C.white} strokeWidth={6} fill="none" strokeLinecap="round" />
    </svg>
  </Tile>
);

// --- накрутка (анимированная): треугольник с «!» пульсирует -----------------------

export const Anomaly: React.FC = () => {
  const frame = useCurrentFrame();
  const phase = (frame % (LOOP / 2)) / (LOOP / 2);
  const pulse = 1 + 0.08 * Math.sin(phase * Math.PI * 2);
  const glow = 0.35 + 0.35 * Math.sin(phase * Math.PI * 2);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <svg viewBox="0 0 100 100" width={96} height={96} style={{ transform: `scale(${pulse})`,
           filter: `drop-shadow(0 0 ${6 + 6 * glow}px rgba(245,165,36,${glow}))` }}>
        <path d="M50 8 L94 88 H6 Z" fill={C.amber} stroke={C.amber} strokeWidth={10} strokeLinejoin="round" />
        <rect x="45" y="34" width="10" height="30" rx="5" fill={C.ink} />
        <circle cx="50" cy="75" r="6" fill={C.ink} />
      </svg>
    </AbsoluteFill>
  );
};

// --- выстрелил (анимированный): последний столбик взлетает -------------------------

export const Spike: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rise = spring({ frame: frame - 8, fps, config: { damping: 8, stiffness: 120 }, durationInFrames: 34 });
  const fall = interpolate(frame, [72, 88], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const height = 18 + 50 * rise * (1 - fall);
  const spark = interpolate(frame, [24, 34, 46], [0, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <Tile bg={C.ink}>
      <svg viewBox="0 0 100 100" width={92} height={92}>
        <rect x="16" y={78 - 22} width="16" height="22" rx="5" fill={C.white} opacity={0.75} />
        <rect x="40" y={78 - 30} width="16" height="30" rx="5" fill={C.white} opacity={0.75} />
        <rect x="64" y={78 - height} width="18" height={height} rx="5" fill={C.blue} />
        {[0, 1, 2, 3, 4].map((index) => {
          const angle = -Math.PI / 2 + (index - 2) * 0.5;
          const r = 8 + 14 * spark;
          return <circle key={index} cx={73 + Math.cos(angle) * r} cy={78 - height - 6 + Math.sin(angle) * r}
                         r={3.2 * spark} fill={C.amberLight} />;
        })}
        <rect x="12" y="80" width="76" height="5" rx="2.5" fill={C.white} opacity={0.35} />
      </svg>
    </Tile>
  );
};

// --- срочная тревога (анимированная): красная точка с расходящимся кольцом ----------

export const Urgent: React.FC = () => {
  const frame = useCurrentFrame();
  const period = LOOP / 2;
  const t = (frame % period) / period;
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <svg viewBox="0 0 100 100" width={100} height={100}>
        <circle cx="50" cy="50" r={24 + 22 * t} fill="none" stroke={C.red} strokeWidth={6 * (1 - t) + 1}
                opacity={1 - t} />
        <circle cx="50" cy="50" r={26} fill={C.red} />
        <circle cx="50" cy="50" r={26} fill="none" stroke={C.redLight} strokeWidth={4} opacity={0.6} />
      </svg>
    </AbsoluteFill>
  );
};

// --- спокойные значки с еле заметной анимацией (src/Subtle.tsx) --------------------

export const PlatformLive: React.FC<{ file: string }> = ({ file }) => <Breathe><Platform file={file} /></Breathe>;
export const RankLive: React.FC<{ place: 1 | 2 | 3 }> = ({ place }) => <Glint radius={44}><Rank place={place} /></Glint>;
export const TrendLive: React.FC<{ dir: "up" | "down" }> = ({ dir }) => (
  <Nudge dy={dir === "up" ? -2 : 2}><Trend dir={dir} /></Nudge>
);
export const PromoLive: React.FC = () => <Sway><Promo /></Sway>;
