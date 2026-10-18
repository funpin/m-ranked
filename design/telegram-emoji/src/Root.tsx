import React from "react";
import { Composition, continueRender, delayRender } from "remotion";
import { BannerLive, TILES } from "./Banner";
import { C, FPS, fontsReady, LOOP, SIZE } from "./brand";
import { Anomaly, Logo, PlatformLive, PromoLive, RankLive, Spike, TrendLive, Urgent } from "./Emoji";
import { Sheet } from "./Sheet";

// Шрифты загружаются один раз до первого кадра.
const waitFonts = delayRender("fonts");
fontsReady.then(() => continueRender(waitFonts));

const W = SIZE * TILES;

export const RemotionRoot: React.FC = () => (
  <>
    {/* Анимированные: WebM VP9 с прозрачностью, 3 с, 30 к/с. */}
    <Composition id="logo" component={Logo} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} />
    <Composition id="spike" component={Spike} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} />
    <Composition id="anomaly" component={Anomaly} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} />
    <Composition id="alert-urgent" component={Urgent} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} />

    {/* Спокойные: та же WebM, движение еле заметное (src/Subtle.tsx). */}
    <Composition id="telegram" component={PlatformLive} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} defaultProps={{ file: "telegram.svg" }} />
    <Composition id="vk" component={PlatformLive} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} defaultProps={{ file: "vk.svg" }} />
    <Composition id="max" component={PlatformLive} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} defaultProps={{ file: "max.svg" }} />
    <Composition id="rutube" component={PlatformLive} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} defaultProps={{ file: "rutube.svg" }} />
    <Composition id="rank-1" component={RankLive} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} defaultProps={{ place: 1 as const }} />
    <Composition id="rank-2" component={RankLive} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} defaultProps={{ place: 2 as const }} />
    <Composition id="rank-3" component={RankLive} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} defaultProps={{ place: 3 as const }} />
    <Composition id="up" component={TrendLive} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} defaultProps={{ dir: "up" as const }} />
    <Composition id="down" component={TrendLive} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} defaultProps={{ dir: "down" as const }} />
    <Composition id="promo" component={PromoLive} durationInFrames={LOOP} fps={FPS} width={SIZE} height={SIZE} />

    {/* Плашки: ролик 500×100, режется на 5 эмодзи (scripts/slice.sh). */}
    <Composition id="band-ours" component={BannerLive} durationInFrames={LOOP} fps={FPS} width={W} height={SIZE}
           defaultProps={{ label: "НАШИ ЛУЧШИЕ", from: C.blue, to: C.blueLight, pictogram: "star" as const }} />
    <Composition id="band-others" component={BannerLive} durationInFrames={LOOP} fps={FPS} width={W} height={SIZE}
           defaultProps={{ label: "ДРУГИЕ ВУЗЫ", from: C.graphite, to: C.graphiteLight, pictogram: "globe" as const }} />
    <Composition id="band-week" component={BannerLive} durationInFrames={LOOP} fps={FPS} width={W} height={SIZE}
           defaultProps={{ label: "НЕДЕЛЯ", from: C.green, to: C.greenLight, pictogram: "calendar" as const }} />
    <Composition id="band-forecast" component={BannerLive} durationInFrames={LOOP} fps={FPS} width={W} height={SIZE}
           defaultProps={{ label: "ПРОГНОЗ", from: C.violet, to: C.violetLight, pictogram: "trend" as const }} />
    <Composition id="band-posts" component={BannerLive} durationInFrames={LOOP} fps={FPS} width={W} height={SIZE}
           defaultProps={{ label: "ПОСТЫ", from: C.blue, to: C.blueLight, pictogram: "list" as const }} />
    <Composition id="band-server" component={BannerLive} durationInFrames={LOOP} fps={FPS} width={W} height={SIZE}
           defaultProps={{ label: "СЕРВЕР", from: C.graphite, to: C.graphiteLight, pictogram: "server" as const }} />
    <Composition id="band-problems" component={BannerLive} durationInFrames={LOOP} fps={FPS} width={W} height={SIZE}
           defaultProps={{ label: "ПРОБЛЕМЫ", from: C.red, to: C.redLight, pictogram: "alert" as const }} />
    <Composition id="band-collection" component={BannerLive} durationInFrames={LOOP} fps={FPS} width={W} height={SIZE}
           defaultProps={{ label: "СБОР", from: C.blue, to: C.blueLight, pictogram: "radar" as const }} />
    <Composition id="band-server2" component={BannerLive} durationInFrames={LOOP} fps={FPS} width={W} height={SIZE}
           defaultProps={{ label: "СЕРВЕР 2", from: C.graphite, to: C.graphiteLight, pictogram: "server" as const }} />

    {/* Лист-превью: как набор выглядит в сообщении на тёмной и светлой теме. */}
    <Composition id="sheet" component={Sheet} durationInFrames={LOOP} fps={FPS} width={1200} height={900} />
  </>
);
