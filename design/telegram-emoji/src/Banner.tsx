import React from "react";
import { fitText } from "@remotion/layout-utils";
import { AbsoluteFill } from "remotion";
import { C, SIZE } from "./brand";
import { Glow } from "./Subtle";

// Плашка-разделитель из TILES эмодзи подряд: одна картинка TILES×100 по 100,
// которую scripts/slice.py режет на квадраты. Telegram ставит кастомные эмодзи
// почти вплотную, поэтому заливка идёт непрерывно через границы квадратов.
export const TILES = 5;

export type Pictogram = "star" | "globe" | "calendar" | "trend" | "list" | "server" | "alert" | "radar";

const PICTOGRAMS: Record<Pictogram, React.ReactNode> = {
  star: <path d="M50 14 l10.6 21.5 23.7 3.4 -17.1 16.7 4 23.6 -21.2 -11.1 -21.2 11.1 4 -23.6 -17.1 -16.7 23.7 -3.4 z"
              fill={C.white} stroke={C.white} strokeWidth={4} strokeLinejoin="round" />,
  globe: <g fill="none" stroke={C.white} strokeWidth={7} strokeLinecap="round">
    <circle cx="50" cy="50" r="34" /><ellipse cx="50" cy="50" rx="14" ry="34" /><path d="M17 40 h66 M17 60 h66" /></g>,
  calendar: <g><rect x="16" y="22" width="68" height="62" rx="12" fill="none" stroke={C.white} strokeWidth={7} />
    <path d="M16 40 h68" stroke={C.white} strokeWidth={7} /><path d="M34 14 v14 M66 14 v14" stroke={C.white} strokeWidth={7} strokeLinecap="round" />
    <text x="50" y="76" textAnchor="middle" fontFamily="Geologica" fontWeight={800} fontSize={30} fill={C.white}>7</text></g>,
  trend: <g fill="none" stroke={C.white} strokeWidth={8} strokeLinecap="round" strokeLinejoin="round">
    <path d="M16 74 L40 50 L56 62 L84 30" /><path d="M64 30 H84 V50" /></g>,
  list: <g stroke={C.white} strokeWidth={8} strokeLinecap="round"><path d="M38 30 H84 M38 50 H84 M38 70 H70" />
    <circle cx="20" cy="30" r="5" fill={C.white} /><circle cx="20" cy="50" r="5" fill={C.white} /><circle cx="20" cy="70" r="5" fill={C.white} /></g>,
  server: <g fill="none" stroke={C.white} strokeWidth={7}><rect x="16" y="18" width="68" height="26" rx="8" />
    <rect x="16" y="56" width="68" height="26" rx="8" /><circle cx="30" cy="31" r="4" fill={C.white} /><circle cx="30" cy="69" r="4" fill={C.white} /></g>,
  alert: <g><path d="M50 12 L90 84 H10 Z" fill="none" stroke={C.white} strokeWidth={8} strokeLinejoin="round" />
    <rect x="45.5" y="38" width="9" height="24" rx="4.5" fill={C.white} /><circle cx="50" cy="72" r="5.5" fill={C.white} /></g>,
  radar: <g fill="none" stroke={C.white} strokeWidth={7} strokeLinecap="round"><circle cx="50" cy="50" r="34" />
    <circle cx="50" cy="50" r="18" /><path d="M50 50 L76 26" /><circle cx="50" cy="50" r="4" fill={C.white} /></g>,
};

type Props = {
  readonly label: string;
  readonly from: string;
  readonly to: string;
  readonly pictogram: Pictogram;
};

// Надпись не больше 50 px и всегда умещается между значком и правым краем.
const TEXT_LEFT = SIZE + 4;
const TEXT_RIGHT_PAD = 26;
const MAX_FONT = 50;

export const Banner: React.FC<Props> = ({ label, from, to, pictogram }) => {
  const width = SIZE * TILES;
  const room = width - TEXT_LEFT - TEXT_RIGHT_PAD;
  const fitted = fitText({ text: label, withinWidth: room, fontFamily: "Geologica", fontWeight: 800,
                           letterSpacing: "1.5px" }).fontSize;
  const fontSize = Math.min(MAX_FONT, Math.floor(fitted));
  // Поля сверху и снизу — 8 px: у соседних строк текста плашки не слипаются.
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 4, right: 4, top: 8, bottom: 8, borderRadius: 26,
                    background: `linear-gradient(90deg, ${from}, ${to})`,
                    boxShadow: "inset 0 -5px 0 rgba(0,0,0,0.16)" }} />
      <svg viewBox="0 0 100 100" width={64} height={64} style={{ position: "absolute", left: 18, top: 18 }}>
        {PICTOGRAMS[pictogram]}
      </svg>
      <div style={{ position: "absolute", left: TEXT_LEFT, width: room, top: 0, bottom: 0,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontFamily: "Geologica", fontWeight: 800, fontSize, letterSpacing: 1.5,
                    color: C.white, whiteSpace: "nowrap", lineHeight: 1, paddingBottom: 3 }}>
        {label}
      </div>
    </AbsoluteFill>
  );
};

// Плашка с еле заметным изменением яркости (для набора; на листе-превью — она же).
export const BannerLive: React.FC<Props> = (props) => <Glow><Banner {...props} /></Glow>;
