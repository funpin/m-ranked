"use client";

import { useEffect, useRef, useState } from "react";
import type { ScenePalette, SceneHandle } from "./hero-scene-three";

/** Цвет CSS-переменной в виде #rrggbb. Токены темы заданы в oklch, которого
 *  three.js не понимает, поэтому цвет прогоняется через холст: браузер сам
 *  переводит его в sRGB. */
function resolveColor(variable: string, probe: CanvasRenderingContext2D) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(variable).trim() || "#888";
  probe.clearRect(0, 0, 1, 1);
  probe.fillStyle = "#000";
  probe.fillStyle = value;
  probe.fillRect(0, 0, 1, 1);
  const [red, green, blue] = probe.getImageData(0, 0, 1, 1).data;
  return `#${[red, green, blue].map((channel) => channel!.toString(16).padStart(2, "0")).join("")}`;
}

function readPalette(): ScenePalette {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const probe = canvas.getContext("2d", { willReadFrequently: true })!;
  return {
    tones: [
      resolveColor("--platform-telegram", probe), resolveColor("--platform-vk", probe),
      resolveColor("--platform-max", probe), resolveColor("--platform-rutube", probe),
    ],
    background: resolveColor("--background", probe),
    // Сетка — цветом текста: на светлой теме цвет рамок сливался с фоном.
    grid: resolveColor("--foreground", probe),
    dark: document.documentElement.dataset.theme === "dark",
  };
}

function webglAvailable() {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

/** Трёхмерный «рельеф замеров» первого экрана. three.js грузится, когда
 *  страница уже отрисована и браузер свободен; до этого и без WebGL на месте
 *  модели — мягкое свечение, текст первого экрана от неё не зависит. */
export function HeroScene() {
  const host = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const hostNode = host.current;
    const canvasNode = canvas.current;
    if (!hostNode || !canvasNode || !webglAvailable()) return;
    let handle: SceneHandle | null = null;
    let cancelled = false;
    const start = () => {
      import("./hero-scene-three").then(({ mountHeroScene }) => {
        if (cancelled) return;
        handle = mountHeroScene(canvasNode, hostNode, {
          palette: readPalette(),
          reduced: matchMedia("(prefers-reduced-motion: reduce)").matches,
          compact: window.innerWidth < 768,
        });
        setReady(true);
      }).catch(() => { /* Без модели первый экран остаётся с подсветкой. */ });
    };
    // Safari без requestIdleCallback — просто короткая пауза.
    const idleSupported = typeof window.requestIdleCallback === "function";
    const idle = idleSupported ? window.requestIdleCallback(start, { timeout: 1200 }) : setTimeout(start, 300);
    // Смена темы перекрашивает модель без перезагрузки.
    const theme = new MutationObserver(() => handle?.setPalette(readPalette()));
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      cancelled = true;
      if (idleSupported) window.cancelIdleCallback(idle as number);
      else clearTimeout(idle);
      theme.disconnect();
      handle?.dispose();
    };
  }, []);

  return (
    <div ref={host} className="landing-hero-scene absolute inset-0" data-testid="hero-scene" data-ready={ready || undefined}>
      <div className="landing-hero-glow absolute inset-0" />
      <canvas ref={canvas} className="absolute inset-0 size-full transition-opacity duration-1000" style={{ opacity: ready ? 1 : 0 }} />
    </div>
  );
}
