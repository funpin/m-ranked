import type { Transition } from "motion/react";

// Общий характер анимаций интерфейса: короткие пружины без отскока. Значения
// animate-ui по умолчанию (scale 0.5, мягкая пружина) — игривее, чем нужно
// строгому аналитическому сайту, поэтому всплывающие элементы появляются из
// почти полного размера и быстро успокаиваются.
export const POP_SPRING: Transition = { type: "spring", stiffness: 420, damping: 32, mass: 0.7 };
// Движение окна — пружина, а прозрачность и размытие — короткий твин: иначе
// текст ещё долго «доостывал» в почти нулевом размытии.
export const PANEL_SPRING: Transition = {
  type: "spring", stiffness: 320, damping: 30,
  opacity: { duration: 0.18, ease: "easeOut" },
  filter: { duration: 0.22, ease: "easeOut" },
};
export const POP_IN = { opacity: 0, scale: 0.94 } as const;
export const POP_SHOWN = { opacity: 1, scale: 1 } as const;

// Модальные окна: подъём с лёгким увеличением и размытием. Переворот
// animate-ui с perspective() оставлял текст окна на 3D-слое, и Chrome рисовал
// его мыльным; в конечной точке здесь трансформации нет, текст чёткий.
export const PANEL_IN = { opacity: 0, y: 12, scale: 0.97, filter: "blur(4px)" } as const;
// В конце фильтр снимается совсем: даже blur(0px) поверх размытого фона
// заставлял Chrome растрировать окно мыльно.
export const PANEL_SHOWN = { opacity: 1, y: 0, scale: 1, filter: "blur(0px)", transitionEnd: { filter: "none" } } as const;
export const FADE_IN = { opacity: 0 } as const;
export const FADE_SHOWN = { opacity: 1 } as const;
