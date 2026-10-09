/**
 * Мазок первого экрана: одна широкая лента с градиентом фирменного синего в
 * фиолетовый, нарисованная как линия роста — подъём, петля и длинный уход
 * вправо вверх. Чистый SVG: при загрузке лента один раз «прорисовывается»
 * (конечная CSS-анимация штриха), дальше градиент медленно переливается
 * (SMIL — не входит в document.getAnimations() и не держит проверки «страница
 * успокоилась»). Цвета берутся из переменных темы: на тёмном фоне лента
 * глубже, чтобы белый текст поверх читался.
 */
const PATH = "M 760 1010 C 880 880 990 760 1090 640 C 1170 545 1240 450 1200 370 C 1160 290 1040 300 1015 375 C 990 455 1080 505 1200 485 C 1300 468 1400 420 1600 330";

export function BrushRibbon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 1440 900" preserveAspectRatio="xMaxYMid slice" aria-hidden="true" data-testid="hero-scene" data-ready="true"
      className={`landing-brush ${className ?? ""}`}>
      <defs>
        <linearGradient id="brush-tone" x1="0" y1="1" x2="1" y2="0" gradientUnits="objectBoundingBox">
          <stop offset="0" stopColor="var(--brush-a)" />
          <stop offset="0.5" stopColor="var(--brush-b)" />
          <stop offset="1" stopColor="var(--brush-c)" />
          <animateTransform attributeName="gradientTransform" type="translate" values="0 0; 0.08 -0.06; 0 0" dur="14s" repeatCount="indefinite" />
        </linearGradient>
        <linearGradient id="brush-sheen" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#fff" stopOpacity="0" />
          <stop offset="0.5" stopColor="#fff" stopOpacity="0.22">
            <animate attributeName="offset" values="-0.3;1.3" dur="9s" repeatCount="indefinite" />
          </stop>
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={PATH} className="landing-brush-stroke" fill="none" stroke="url(#brush-tone)" strokeWidth="132" strokeLinecap="butt" strokeLinejoin="round" pathLength={1} />
      <path d={PATH} className="landing-brush-stroke landing-brush-sheen" fill="none" stroke="url(#brush-sheen)" strokeWidth="132" strokeLinecap="butt" strokeLinejoin="round" pathLength={1} />
    </svg>
  );
}
