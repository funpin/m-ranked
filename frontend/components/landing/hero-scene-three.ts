/** Трёхмерная модель первого экрана на three.js. Модуль грузится отдельным
 *  фрагментом уже после первой отрисовки (см. hero-scene.tsx), поэтому в
 *  первую загрузку главной не входит.
 *
 *  Рельеф замеров: кривые накопления просмотров постов в цветах площадок,
 *  под каждой — полупрозрачная «стенка», на ведущих кривых — точки замеров и
 *  бегущий новый замер. При прокрутке камера опускается из косого ракурса во
 *  фронтальный: рельеф превращается в обычный график. Указатель мыши слегка
 *  поворачивает модель. */
import {
  AdditiveBlending, BufferAttribute, BufferGeometry, CanvasTexture, CatmullRomCurve3, Color, DoubleSide, Fog, GridHelper,
  Group, InstancedMesh, Matrix4, Mesh, MeshBasicMaterial, NormalBlending, PerspectiveCamera, Scene, SphereGeometry, Sprite,
  SpriteMaterial, TubeGeometry, Vector3, WebGLRenderer, type Blending, type Material,
} from "three";
import { sceneCurves } from "@/lib/landing";

export type ScenePalette = { tones: readonly [string, string, string, string]; background: string; grid: string; dark: boolean };
export type SceneOptions = { palette: ScenePalette; reduced: boolean; compact: boolean };
export type SceneHandle = { setPalette(palette: ScenePalette): void; dispose(): void };

const TUBE_SEGMENTS = 72;
const TUBE_SIDES = 6;
const GROW_SECONDS = 2.4;
const PROBE_SECONDS = 7;
const TARGET = new Vector3(0.3, 0.85, 0);

const clamp = (value: number, low = 0, high = 1) => Math.min(high, Math.max(low, value));
const ease = (value: number) => 1 - (1 - value) ** 3;
const smooth = (value: number) => value * value * (3 - 2 * value);
const lerp = (from: number, to: number, amount: number) => from + (to - from) * amount;

/** Мягкое свечение для бегущего замера. */
function glowTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 64;
  const context = canvas.getContext("2d")!;
  const gradient = context.createRadialGradient(32, 32, 0, 32, 32, 32);
  gradient.addColorStop(0, "rgba(255,255,255,1)");
  gradient.addColorStop(0.35, "rgba(255,255,255,0.35)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, 64, 64);
  return new CanvasTexture(canvas);
}

/** «Стенка» под кривой: сверху цвет площадки, к полу — прозрачность. */
function wallGeometry(curve: CatmullRomCurve3, segments: number) {
  const positions = new Float32Array((segments + 1) * 2 * 3);
  const alpha = new Float32Array((segments + 1) * 2 * 4);
  const index: number[] = [];
  for (let step = 0; step <= segments; step += 1) {
    const point = curve.getPoint(step / segments);
    positions.set([point.x, point.y, point.z, point.x, 0, point.z], step * 6);
    alpha.set([1, 1, 1, 1, 1, 1, 1, 0], step * 8);
    if (step < segments) {
      const top = step * 2;
      index.push(top, top + 1, top + 2, top + 1, top + 3, top + 2);
    }
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new BufferAttribute(positions, 3));
  geometry.setAttribute("color", new BufferAttribute(alpha, 4));
  geometry.setIndex(index);
  return geometry;
}

export function mountHeroScene(canvas: HTMLCanvasElement, host: HTMLElement, options: SceneOptions): SceneHandle {
  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
  // Холст на всю ширину окна: выше 1.25 плотность пикселей почти не видна, а
  // заливка растёт квадратично и даёт подёргивания на встроенной графике.
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.25));
  renderer.setClearColor(0x000000, 0);

  const scene = new Scene();
  const camera = new PerspectiveCamera(30, 1, 0.1, 60);
  const model = new Group();
  scene.add(model);

  const data = sceneCurves();
  const glow = glowTexture();
  const tubeMaterials: MeshBasicMaterial[] = [];
  const wallMaterials: MeshBasicMaterial[] = [];
  const toneOf = new Map<Material, number>();
  const growing: { geometry: BufferGeometry; count: number; stride: number; delay: number }[] = [];
  const probes: { curve: CatmullRomCurve3; dot: Mesh; halo: Sprite; offset: number }[] = [];
  const marks: { mesh: InstancedMesh; points: Vector3[]; start: number; end: number; delay: number }[] = [];
  const matrix = new Matrix4();

  for (const [index, item] of data.entries()) {
    const curve = new CatmullRomCurve3(item.points.map(([x, y, z]) => new Vector3(x, y, z)));
    const tube = new TubeGeometry(curve, TUBE_SEGMENTS, item.lead ? 0.022 : 0.008, TUBE_SIDES, false);
    const tubeMaterial = new MeshBasicMaterial({ transparent: true, opacity: item.lead ? 1 : 0.32, depthWrite: false });
    tubeMaterials.push(tubeMaterial);
    toneOf.set(tubeMaterial, item.tone);
    model.add(new Mesh(tube, tubeMaterial));
    growing.push({ geometry: tube, count: tube.index!.count, stride: TUBE_SIDES * 6, delay: item.delay });

    if (!item.lead) continue;
    // Стенка — только под ведущей кривой: она и даёт объём.
    const wall = wallGeometry(curve, TUBE_SEGMENTS);
    const wallMaterial = new MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.14, side: DoubleSide, depthWrite: false });
    wallMaterials.push(wallMaterial);
    toneOf.set(wallMaterial, item.tone);
    model.add(new Mesh(wall, wallMaterial));
    growing.push({ geometry: wall, count: wall.index!.count, stride: 6, delay: item.delay });

    // Точки замеров на ведущих кривых: кривая проходит через каждую из них.
    const points = item.points.filter((_, step) => step % 2 === 1 && step > 0).map(([x, y, z]) => new Vector3(x, y, z));
    const dots = new InstancedMesh(new SphereGeometry(0.032, 10, 10), tubeMaterial, points.length);
    model.add(dots);
    marks.push({ mesh: dots, points, start: item.points[0]![0], end: item.points.at(-1)![0], delay: item.delay });

    const dot = new Mesh(new SphereGeometry(0.055, 14, 14), tubeMaterial);
    const halo = new Sprite(new SpriteMaterial({ map: glow, transparent: true, depthWrite: false, blending: AdditiveBlending }));
    halo.scale.setScalar(0.5);
    toneOf.set(halo.material, item.tone);
    dot.visible = halo.visible = false;
    model.add(dot, halo);
    probes.push({ curve, dot, halo, offset: index * 0.37 });
  }

  let grid = new GridHelper(8, 12);
  model.add(grid);

  function setPalette(palette: ScenePalette) {
    const blending: Blending = palette.dark ? AdditiveBlending : NormalBlending;
    const tones = palette.tones.map((tone) => new Color(tone));
    for (const material of [...tubeMaterials, ...wallMaterials]) {
      material.color.copy(tones[toneOf.get(material)!]!);
      material.blending = blending;
      material.needsUpdate = true;
    }
    for (const probe of probes) (probe.halo.material as SpriteMaterial).color.copy(tones[toneOf.get(probe.halo.material)!]!);
    scene.fog = new Fog(new Color(palette.background), 7, 15);
    model.remove(grid);
    grid.geometry.dispose();
    (grid.material as Material).dispose();
    grid = new GridHelper(8, 12, new Color(palette.grid), new Color(palette.grid));
    const gridMaterial = grid.material as Material;
    gridMaterial.transparent = true;
    gridMaterial.opacity = palette.dark ? 0.16 : 0.3;
    model.add(grid);
    render();
  }

  // Прокрутка и указатель — цели, к которым камера плавно подтягивается.
  let scroll = 0;
  let pointerX = 0;
  let pointerY = 0;
  const view = { azimuth: -0.62, elevation: 0.42 };
  const readScroll = () => {
    const bounds = host.getBoundingClientRect();
    scroll = clamp(-bounds.top / Math.max(1, bounds.height * 0.85));
  };
  const onPointer = (event: PointerEvent) => {
    if (event.pointerType !== "mouse") return;
    pointerX = (event.clientX / window.innerWidth) * 2 - 1;
    pointerY = (event.clientY / window.innerHeight) * 2 - 1;
  };

  let width = 1;
  let height = 1;
  function resize() {
    width = Math.max(1, host.clientWidth);
    height = Math.max(1, host.clientHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    // На широком экране модель стоит справа от текста: кадр — левая часть
    // более широкого поля, центр которого смещён вправо.
    const shift = options.compact ? 0 : clamp((width / height - 1) * 0.36, 0, 0.32);
    camera.setViewOffset(width * (1 + 2 * shift), height, 0, 0, width, height);
    render();
  }

  function place(time: number) {
    const progress = smooth(scroll);
    const idle = options.reduced ? 0 : Math.sin(time * 0.12) * 0.05;
    const targetAzimuth = lerp(-0.62, -0.04, progress) + pointerX * 0.16 + idle;
    const targetElevation = lerp(0.42, 0.08, progress) - pointerY * 0.06;
    const follow = options.reduced ? 1 : 0.06;
    view.azimuth += (targetAzimuth - view.azimuth) * follow;
    view.elevation += (targetElevation - view.elevation) * follow;
    const distance = lerp(options.compact ? 13 : 13.2, 10.5, progress);
    // На телефоне текст занимает почти весь экран: модель опускается под него.
    const lift = options.compact ? 1.6 : 0;
    camera.position.set(
      TARGET.x + distance * Math.cos(view.elevation) * Math.sin(view.azimuth),
      TARGET.y + distance * Math.sin(view.elevation) + lift,
      TARGET.z + distance * Math.cos(view.elevation) * Math.cos(view.azimuth),
    );
    camera.lookAt(TARGET.x, TARGET.y + lift, TARGET.z);
  }

  let grown = false;
  function grow(time: number) {
    // После появления геометрия больше не меняется: пересчёт не нужен.
    const complete = options.reduced || time > GROW_SECONDS + 1.3;
    if (!grown) for (const item of growing) {
      const share = options.reduced ? 1 : ease(clamp((time - item.delay * 0.6) / GROW_SECONDS));
      item.geometry.setDrawRange(0, Math.round((item.count / item.stride) * share) * item.stride);
    }
    grown = complete;
    for (const mark of marks) {
      const share = options.reduced ? 1 : ease(clamp((time - mark.delay * 0.6) / GROW_SECONDS));
      const reach = lerp(mark.start, mark.end, share);
      mark.points.forEach((point, dot) => {
        // Недавний замер чуть крупнее: сбор идёт прямо сейчас.
        const size = point.x > reach ? 0 : options.reduced ? 1 : 1 + 0.25 * Math.max(0, Math.sin(time * 2 - dot * 0.6));
        matrix.makeScale(size, size, size).setPosition(point);
        mark.mesh.setMatrixAt(dot, matrix);
      });
      mark.mesh.instanceMatrix.needsUpdate = true;
    }
    for (const probe of probes) {
      const visible = !options.reduced && time > GROW_SECONDS + 0.4;
      probe.dot.visible = probe.halo.visible = visible;
      if (!visible) continue;
      const u = ease(((time / PROBE_SECONDS + probe.offset) % 1));
      const point = probe.curve.getPointAt(u);
      probe.dot.position.copy(point);
      probe.halo.position.copy(point);
    }
  }

  const started = performance.now();
  function render() {
    const time = (performance.now() - started) / 1000;
    place(time);
    grow(time);
    renderer.render(scene, camera);
  }

  // Кадры идут, только пока первый экран виден и вкладка открыта.
  let frame = 0;
  let onScreen = true;
  const loop = () => {
    frame = 0;
    if (!onScreen || document.hidden) return;
    render();
    frame = requestAnimationFrame(loop);
  };
  const wake = () => { if (!frame && !options.reduced) frame = requestAnimationFrame(loop); };
  const visibility = new IntersectionObserver(([entry]) => { onScreen = Boolean(entry?.isIntersecting); if (onScreen) wake(); });
  visibility.observe(host);
  const sizes = new ResizeObserver(resize);
  sizes.observe(host);
  const onScroll = () => { readScroll(); if (options.reduced) render(); };
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("pointermove", onPointer, { passive: true });
  document.addEventListener("visibilitychange", wake);

  readScroll();
  setPalette(options.palette);
  resize();
  wake();

  return {
    setPalette,
    dispose() {
      cancelAnimationFrame(frame);
      visibility.disconnect();
      sizes.disconnect();
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("pointermove", onPointer);
      document.removeEventListener("visibilitychange", wake);
      scene.traverse((object) => {
        const mesh = object as Mesh;
        mesh.geometry?.dispose();
        const material = mesh.material as Material | Material[] | undefined;
        for (const item of Array.isArray(material) ? material : material ? [material] : []) item.dispose();
      });
      glow.dispose();
      renderer.dispose();
    },
  };
}
