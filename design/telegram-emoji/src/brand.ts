import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

// Шрифты сайта m-ranked: Geologica — заголовки и надписи, JetBrains Mono — цифры.
export const fontsReady = Promise.all([
  loadFont({ family: "Geologica", url: staticFile("Geologica-Variable.ttf"), weight: "100 900" }),
  loadFont({ family: "JetBrains Mono", url: staticFile("JetBrainsMono-Variable.ttf"), weight: "100 800" }),
]);

// Цвета — из frontend/app/globals.css и логотипа (frontend/public/icons/app-icon.svg).
export const C = {
  ink: "#0d1117",
  white: "#ffffff",
  blue: "#0082fe",
  blueLight: "#36a3ff",
  graphite: "#3b3e48",
  graphiteLight: "#5b606e",
  green: "#0f8f6a",
  greenLight: "#22b98a",
  up: "#3ad29f",
  down: "#ff6b6b",
  violet: "#7b4dff",
  violetLight: "#a77bff",
  amber: "#f5a524",
  amberLight: "#ffc857",
  red: "#e5484d",
  redLight: "#ff6b6b",
  gold: "#f5c542",
  silver: "#c9ced6",
  bronze: "#d39a62",
} as const;

// Три пути знака m-ranked (координаты 0..589 × 0..344), без фона.
export const LOGO_PATHS = [
  { d: "M23 0h89c53 0 96 43 96 96v225c0 13-10 23-23 23H23c-13 0-23-10-23-23V23C0 10 10 0 23 0Z", fill: C.white },
  { d: "M256 0h73c47 0 85 43 85 96v225c0 13-10 23-23 23H256c-13 0-23-10-23-23V23c0-13 10-23 23-23Z", fill: C.blue },
  { d: "M458 0h39c51 0 92 43 92 96v225c0 13-10 23-23 23H462c-13 0-23-10-23-23V23c0-13 8-23 19-23Z", fill: C.white },
] as const;

export const SIZE = 100; // кастомный эмодзи Telegram — ровно 100×100
export const FPS = 30;
export const LOOP = 90; // 3 секунды — предел Telegram для видео-эмодзи
