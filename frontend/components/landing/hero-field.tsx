import { heroCurves } from "@/lib/landing";

const TONES = ["var(--platform-telegram)", "var(--platform-vk)", "var(--platform-max)", "var(--platform-rutube)"] as const;
const CURVES = heroCurves();

/** Фон первого экрана: поле кривых накопления просмотров в цветах площадок.
 *  Рисуется на сервере и анимируется только CSS и SVG — ни байта скрипта. */
export function HeroField() {
  return (
    <svg className="landing-hero-field" viewBox="0 0 1440 720" preserveAspectRatio="xMidYMax slice" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="hero-fade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="white" stopOpacity="0" />
          <stop offset="0.35" stopColor="white" stopOpacity="0.9" />
          <stop offset="1" stopColor="white" stopOpacity="1" />
        </linearGradient>
        <mask id="hero-mask">
          <rect width="1440" height="720" fill="url(#hero-fade)" />
        </mask>
        <filter id="hero-glow" x="-10%" y="-10%" width="120%" height="120%">
          <feGaussianBlur stdDeviation="4" />
        </filter>
      </defs>
      <g className="landing-hero-drift" mask="url(#hero-mask)" fill="none" strokeLinecap="round">
        {CURVES.map((curve, index) => (
          <g key={index} style={{ color: TONES[curve.tone] }}>
            {curve.lead && <path d={curve.d} stroke="currentColor" strokeWidth={6} opacity={0.35} filter="url(#hero-glow)"
              className="landing-hero-curve" pathLength={1} style={{ animationDelay: `${curve.delay}s` }} />}
            <path d={curve.d} stroke="currentColor" strokeWidth={curve.width} opacity={curve.opacity}
              className="landing-hero-curve" pathLength={1} style={{ animationDelay: `${curve.delay}s` }} />
            {curve.marks.map(([x, y], mark) => (
              <circle key={mark} cx={x} cy={y} r={2.4} fill="currentColor" className="landing-hero-mark"
                style={{ animationDelay: `${curve.delay + 0.9 + mark * 0.06}s` }} />
            ))}
            {curve.lead && (
              // Новый замер бежит по кривой: сбор идёт прямо сейчас.
              <circle r={4} fill="currentColor" className="landing-hero-probe">
                <animateMotion dur={`${9 + curve.tone * 1.5}s`} begin={`${curve.delay + 1.8}s`} repeatCount="indefinite"
                  keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines="0.3 0 0.2 1" path={curve.d} />
              </circle>
            )}
          </g>
        ))}
      </g>
    </svg>
  );
}
