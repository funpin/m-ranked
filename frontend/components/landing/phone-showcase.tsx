import type { CSSProperties, ReactNode } from "react";
import { PlatformLogo } from "@/components/platform-logo";
import { KNOWN_PLATFORMS, formatStat, type PhoneNetwork } from "@/lib/landing";

/** Телефон, уже лежащий с наклоном, — как на страницах Apple. Корпус —
 *  готовый снимок собственной модели (без чужих фирменных примет), экран —
 *  живая разметка, положенная в ту же перспективу. При первом появлении
 *  телефон всплывает на место, а на чёрном экране по очереди проявляются
 *  площадки, столбики и итоги. Один раз: прокрутка назад его не сворачивает. */
export function PhoneShowcase({ children }: { children?: ReactNode }) {
  return (
    // Прозрачность меняется у обёртки, а движение — у самого телефона.
    <div className="landing-phone-stage landing-phone-reveal" data-testid="phone-showcase">
      <div className="landing-phone">
        {/* eslint-disable-next-line @next/next/no-img-element -- снимок уже сжат в нужные размеры */}
        <img className="landing-phone-photo" src="/landing/phone-2400.webp" alt="" aria-hidden="true"
          srcSet="/landing/phone-1200.webp 1200w, /landing/phone-2400.webp 2400w" sizes="min(92vw, 1120px)"
          width={2400} height={802} loading="lazy" decoding="async" />
        <div className="landing-phone-view">
          <div className="landing-phone-screen">
            <span className="landing-phone-camera" aria-hidden="true" />
            <div className="landing-phone-app">{children}</div>
            <span className="landing-phone-glare" aria-hidden="true" />
          </div>
        </div>
      </div>
    </div>
  );
}

const TONE = (platform: string) => `var(--platform-${platform})`;

/** Экран телефона: сравнение активности площадок за 30 дней по всем вузам.
 *  Слева — площадки с долей просмотров, справа — просмотры по дням
 *  столбиками по площадкам, внизу — типичный пост за сутки. */
export function PhoneDashboard({ days, networks }: { days: string[]; networks: PhoneNetwork[] }) {
  const totalViews = networks.reduce((sum, network) => sum + network.views, 0) || 1;
  const perDay = days.map((_, index) => networks.reduce((sum, network) => sum + (network.daily[index] ?? 0), 0));
  const peak = Math.max(1, ...perDay);
  const barWidth = 100 / Math.max(1, days.length);
  return (
    <div className="landing-phone-dashboard" role="img"
      aria-label={`Сравнение площадок за 30 дней: ${networks.map((network) => `${KNOWN_PLATFORMS[network.platform].name} — ${formatStat(network.views)} просмотров`).join(", ")}`}>
      <header className="landing-phone-bar">
        <span className="font-semibold">Сравнение площадок</span>
        <span className="text-white/55">все вузы · 30 дней</span>
      </header>
      <div className="landing-phone-body">
        <ul className="landing-phone-tracks">
          {networks.map((network, index) => (
            <li key={network.platform} style={{ "--tone": TONE(network.platform), "--i": index } as CSSProperties}>
              <PlatformLogo platform={network.platform} size={40} decorative className="landing-phone-logo" />
              <span className="landing-phone-track-name">{KNOWN_PLATFORMS[network.platform].name}</span>
              <span className="landing-phone-track-value">{formatStat(network.views)}</span>
              <span className="landing-phone-slider"><i style={{ width: `${Math.max(4, (network.views / totalViews) * 100)}%` }} /></span>
            </li>
          ))}
        </ul>
        <div className="landing-phone-chart">
          <svg viewBox="0 0 100 60" preserveAspectRatio="none" aria-hidden="true" className="landing-phone-bars">
            {[15, 30, 45].map((y) => <line key={y} x1={0} x2={100} y1={y} y2={y} stroke="white" strokeOpacity={0.07} strokeWidth={0.2} />)}
            {days.map((day, index) => {
              let top = 60;
              return networks.map((network) => {
                const height = ((network.daily[index] ?? 0) / peak) * 56;
                top -= height;
                return height > 0 ? (
                  <rect key={`${day}-${network.platform}`} x={index * barWidth + barWidth * 0.14} y={top} width={barWidth * 0.72}
                    height={height} rx={0.35} fill={TONE(network.platform)} fillOpacity={0.92} style={{ "--i": index } as CSSProperties} />
                ) : null;
              });
            })}
          </svg>
          <div className="landing-phone-pads">
            {networks.map((network, index) => (
              <div key={network.platform} style={{ "--tone": TONE(network.platform), "--i": index } as CSSProperties}>
                <span className="landing-phone-pad-value">{network.views24 === null ? "—" : formatStat(network.views24)}</span>
                <span className="landing-phone-pad-label">за сутки · {KNOWN_PLATFORMS[network.platform].name}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
