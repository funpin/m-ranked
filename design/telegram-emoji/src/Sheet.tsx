import React from "react";
import { AbsoluteFill } from "remotion";
import { BannerLive as Banner, TILES } from "./Banner";
import { C, SIZE } from "./brand";
import { Anomaly, Logo, PlatformLive as Platform, PromoLive as Promo, RankLive as Rank, Spike, TrendLive as Trend, Urgent } from "./Emoji";

// Превью набора: каждый эмодзи в размере строки текста Telegram (~22 px) и
// крупно, на тёмной и светлой теме. Не загружается в Telegram.

const At: React.FC<{ size: number; width?: number; children: React.ReactNode }> = ({ size, width = 1, children }) => (
  <span style={{ display: "inline-block", width: size * width, height: size, position: "relative",
                 verticalAlign: "middle", margin: "0 1px" }}>
    <span style={{ position: "absolute", left: 0, top: 0, width: SIZE * width, height: SIZE,
                   transform: `scale(${size / SIZE})`, transformOrigin: "0 0" }}>{children}</span>
  </span>
);

const ICONS: Array<[string, React.ReactNode]> = [
  ["logo", <Logo />], ["telegram", <Platform file="telegram.svg" />], ["vk", <Platform file="vk.svg" />],
  ["max", <Platform file="max.svg" />], ["rutube", <Platform file="rutube.svg" />], ["rank 1", <Rank place={1} />],
  ["rank 2", <Rank place={2} />], ["rank 3", <Rank place={3} />], ["up", <Trend dir="up" />],
  ["down", <Trend dir="down" />], ["promo", <Promo />], ["anomaly", <Anomaly />], ["spike", <Spike />],
  ["urgent", <Urgent />],
];

const Message: React.FC<{ dark: boolean }> = ({ dark }) => {
  const s = 24;
  const text = dark ? "#e9edf1" : "#111";
  const link = dark ? "#6ab3f3" : "#2a7ae2";
  return (
    <div style={{ background: dark ? "#182533" : "#ffffff", color: text, borderRadius: 18, padding: "16px 18px",
                  fontFamily: "-apple-system, system-ui, sans-serif", fontSize: 20, lineHeight: "30px", width: 520 }}>
      <div><At size={s}><Logo /></At> <b>Дайджест · МФТИ · 12–18 окт</b></div>
      <div style={{ height: 8 }} />
      <div><At size={s} width={TILES}><Banner label="НАШИ ЛУЧШИЕ" from={C.blue} to={C.blueLight} pictogram="star" /></At></div>
      <div><At size={s}><Platform file="telegram.svg" /></At> <At size={s}><Rank place={1} /></At>{" "}
        <span style={{ color: link, textDecoration: "underline" }}>альбом</span> · ×2,3 · 2,9 тыс. просм.</div>
      <div><At size={s}><Platform file="vk.svg" /></At> <At size={s}><Rank place={2} /></At>{" "}
        <span style={{ color: link, textDecoration: "underline" }}>фото</span> · ×11,2 · 2,3 тыс. <At size={s}><Promo /></At></div>
      <div style={{ height: 8 }} />
      <div><At size={s} width={TILES}><Banner label="НЕДЕЛЯ" from={C.green} to={C.greenLight} pictogram="calendar" /></At></div>
      <div><At size={s}><Platform file="max.svg" /></At> <b>11,3 тыс.</b> просм. <At size={s}><Trend dir="up" /></At> +12 %</div>
      <div><At size={s}><Spike /></At> Наш пост выстрелил · <At size={s}><Anomaly /></At> Накрутка · <At size={s}><Urgent /></At> Срочно</div>
    </div>
  );
};

export const Sheet: React.FC = () => (
  <AbsoluteFill style={{ background: "#0e1117", padding: 28, gap: 22, display: "flex", flexDirection: "column" }}>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
      {ICONS.map(([name, node]) => (
        <div key={name} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
                                 color: "#8b949e", fontFamily: "Geologica", fontSize: 13 }}>
          <At size={64}>{node}</At>{name}
        </div>
      ))}
    </div>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
      {([["НАШИ ЛУЧШИЕ", C.blue, C.blueLight, "star"], ["ДРУГИЕ ВУЗЫ", C.graphite, C.graphiteLight, "globe"],
         ["НЕДЕЛЯ", C.green, C.greenLight, "calendar"], ["ПРОГНОЗ", C.violet, C.violetLight, "trend"],
         ["ПРОБЛЕМЫ", C.red, C.redLight, "alert"], ["СБОР", C.blue, C.blueLight, "radar"],
         ["СЕРВЕР 2", C.graphite, C.graphiteLight, "server"], ["ПОСТЫ", C.blue, C.blueLight, "list"]] as const)
        .map(([label, from, to, pictogram]) => (
          <At key={label} size={52} width={TILES}><Banner label={label} from={from} to={to} pictogram={pictogram} /></At>
        ))}
    </div>
    <div style={{ display: "flex", gap: 24 }}>
      <Message dark />
      <Message dark={false} />
    </div>
  </AbsoluteFill>
);
