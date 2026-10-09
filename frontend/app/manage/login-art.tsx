/** Иллюстрация к форме входа: знак m-ranked из трёх столбцов на тёмном
 *  «стекле», вокруг — карточки того, чем живёт панель: рейтинг вузов, рост
 *  просмотров, четыре площадки и второй фактор. Чистый SVG без запросов:
 *  страница входа не тянет ни картинок, ни скриптов ради украшения.
 *  Анимация — только плавное покачивание и отключается при reduced motion. */
export function LoginArt() {
  return (
    <svg viewBox="0 0 440 500" preserveAspectRatio="xMidYMid slice" role="img" aria-label="Знак m-ranked и карточки мониторинга"
      className="login-art absolute inset-0 size-full font-sans">
      <defs>
        <linearGradient id="la-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#0b0d12" />
          <stop offset="1" stopColor="#14161d" />
        </linearGradient>
        <radialGradient id="la-blue" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#0082fe" stopOpacity="0.55" />
          <stop offset="1" stopColor="#0082fe" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="la-violet" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#7b4dff" stopOpacity="0.4" />
          <stop offset="1" stopColor="#7b4dff" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="la-teal" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#1fb6c9" stopOpacity="0.32" />
          <stop offset="1" stopColor="#1fb6c9" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="la-glass" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.14" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0.04" />
        </linearGradient>
        <linearGradient id="la-bar" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#f5f5f7" />
          <stop offset="1" stopColor="#b9bcc6" />
        </linearGradient>
        <linearGradient id="la-bar-blue" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#4aa8ff" />
          <stop offset="1" stopColor="#0066d6" />
        </linearGradient>
        <linearGradient id="la-line" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#1fb6c9" />
          <stop offset="1" stopColor="#4aa8ff" />
        </linearGradient>
        <linearGradient id="la-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#4aa8ff" stopOpacity="0.35" />
          <stop offset="1" stopColor="#4aa8ff" stopOpacity="0" />
        </linearGradient>
        <pattern id="la-dots" width="16" height="16" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="1" fill="#ffffff" fillOpacity="0.07" />
        </pattern>
        <filter id="la-shadow" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="14" stdDeviation="14" floodColor="#000000" floodOpacity="0.45" />
        </filter>
      </defs>

      <rect width="440" height="500" fill="url(#la-bg)" />
      <g transform="translate(20 -26)">
      <circle cx="210" cy="250" r="230" fill="url(#la-blue)" />
      <circle cx="360" cy="80" r="170" fill="url(#la-violet)" />
      <circle cx="40" cy="500" r="190" fill="url(#la-teal)" />
      </g>
      <rect width="440" height="500" fill="url(#la-dots)" />
      <g transform="translate(20 -26)">

      {/* Знак: три столбца, как в логотипе, средний — фирменный синий. */}
      <g className="la-float-slow" filter="url(#la-shadow)">
        <g transform="translate(118 196) scale(0.28)">
          <path fill="url(#la-bar)" d="M23 0h89c53 0 96 43 96 96v225c0 13-10 23-23 23H23c-13 0-23-10-23-23V23C0 10 10 0 23 0Z" />
          <path fill="url(#la-bar-blue)" d="M256 0h73c47 0 85 43 85 96v225c0 13-10 23-23 23H256c-13 0-23-10-23-23V23c0-13 10-23 23-23Z" />
          <path fill="url(#la-bar)" d="M458 0h39c51 0 92 43 92 96v225c0 13-10 23-23 23H462c-13 0-23-10-23-23V23c0-13 8-23 19-23Z" />
        </g>
      </g>

      {/* Рейтинг: три строки с полосами. */}
      <g className="la-float-a" filter="url(#la-shadow)">
        <rect x="28" y="52" width="176" height="112" rx="14" fill="url(#la-glass)" stroke="#ffffff" strokeOpacity="0.14" />
        <text x="44" y="78" fill="#ffffff" fillOpacity="0.62" fontSize="10" fontWeight="500">М‑Рейтинг · соцсети</text>
        {[[0, 112, "#4aa8ff"], [1, 88, "#a68bff"], [2, 64, "#5fd3c4"]].map(([row, width, color]) => (
          <g key={row as number} transform={`translate(44 ${94 + (row as number) * 22})`}>
            <text x="0" y="9" fill="#ffffff" fontSize="10" fontWeight="600">{(row as number) + 1}</text>
            <rect x="16" y="1" width="128" height="9" rx="4.5" fill="#ffffff" fillOpacity="0.08" />
            <rect x="16" y="1" width={width as number} height="9" rx="4.5" fill={color as string} />
          </g>
        ))}
      </g>

      {/* Динамика: линия роста просмотров. */}
      <g className="la-float-b" filter="url(#la-shadow)">
        <rect x="196" y="388" width="176" height="112" rx="14" fill="url(#la-glass)" stroke="#ffffff" strokeOpacity="0.14" />
        <text x="212" y="414" fill="#ffffff" fillOpacity="0.62" fontSize="10" fontWeight="500">Просмотры · 24 ч</text>
        <text x="356" y="414" fill="#5fd3c4" fontSize="10" fontWeight="600" textAnchor="end">+18%</text>
        <path d="M212 482 C232 478 240 470 256 468 S282 456 298 450 S326 436 340 428 L356 422 L356 488 L212 488 Z" fill="url(#la-area)" />
        <path d="M212 482 C232 478 240 470 256 468 S282 456 298 450 S326 436 340 428 L356 422" fill="none" stroke="url(#la-line)" strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="356" cy="422" r="4" fill="#4aa8ff" stroke="#0b0d12" strokeWidth="2" />
      </g>

      {/* Четыре площадки сбора. */}
      <g className="la-float-c" filter="url(#la-shadow)">
        <rect x="236" y="132" width="136" height="44" rx="22" fill="url(#la-glass)" stroke="#ffffff" strokeOpacity="0.14" />
        {["#2aa3e0", "#4c75ff", "#8a5cff", "#ff4b4b"].map((color, index) => (
          <circle key={color} cx={258 + index * 22} cy="154" r="8" fill={color} />
        ))}
        <circle cx="350" cy="154" r="3.5" fill="#5fd3c4">
          <animate attributeName="opacity" values="1;0.25;1" dur="2.4s" repeatCount="3" />
        </circle>
      </g>

      {/* Второй фактор: щит и шесть ячеек кода. */}
      <g className="la-float-b" filter="url(#la-shadow)">
        <rect x="28" y="406" width="148" height="76" rx="14" fill="url(#la-glass)" stroke="#ffffff" strokeOpacity="0.14" />
        <path d="M52 424 l12 5 v9 c0 8 -5 13 -12 16 c-7 -3 -12 -8 -12 -16 v-9 Z" fill="none" stroke="#4aa8ff" strokeWidth="2" strokeLinejoin="round" />
        <path d="M47 437 l4 4 l7 -8" fill="none" stroke="#4aa8ff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <text x="74" y="438" fill="#ffffff" fontSize="10" fontWeight="600">2FA</text>
        <text x="74" y="451" fill="#ffffff" fillOpacity="0.55" fontSize="9">код одноразовый</text>
        {Array.from({ length: 6 }, (_, index) => (
          <rect key={index} x={42 + index * 20} y="460" width="16" height="12" rx="3" fill="#ffffff" fillOpacity={index < 4 ? 0.22 : 0.08} />
        ))}
      </g>

      <text x="200" y="330" fill="#ffffff" fontSize="20" fontWeight="700" textAnchor="middle" letterSpacing="-0.4">m-ranked</text>
      <text x="200" y="350" fill="#ffffff" fillOpacity="0.55" fontSize="10.5" textAnchor="middle">панель управления</text>
      </g>
    </svg>
  );
}
