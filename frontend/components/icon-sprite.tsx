/**
 * Один набор контуров на страницу вместо повторения их в каждой иконке.
 *
 * В обзоре 408 значков, различных среди них девять: одна «ⓘ» встречается 251
 * раз. Каждый значок приезжал собственным элементом со своими контурами — 143
 * КБ разметки и столько же в служебной нагрузке React, плюс по несколько
 * элементов на отрисовку. Здесь контуры объявлены один раз, а значок
 * ссылается на объявление.
 *
 * Контуры взяты из той же библиотеки, что рисовала их раньше, и совпадают с
 * ней символ в символ: обводка, толщина и скругления заданы на самом наборе,
 * цвет наследуется от текста, как и прежде.
 */
export const ICON_NAMES = ["info", "file-text", "trending-up", "trending-down",
                           "plus", "minus", "heart", "eye", "message-circle", "repeat-2"] as const;
export type IconName = (typeof ICON_NAMES)[number];

export function IconSprite() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true" className="icon"
      style={{ position: "absolute", width: 0, height: 0, overflow: "hidden" }}>
      <defs>
        <g id="i-heart">
          <path d="M2 9.5a5.5 5.5 0 0 1 9.591-3.676.56.56 0 0 0 .818 0A5.49 5.49 0 0 1 22 9.5c0 2.29-1.5 4-3 5.5l-5.492 5.313a2 2 0 0 1-3 .019L5 15c-1.5-1.5-3-3.2-3-5.5" />
        </g>
        <g id="i-eye">
          <path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" />
          <circle cx="12" cy="12" r="3" />
        </g>
        <g id="i-message-circle">
          <path d="M2.992 16.342a2 2 0 0 1 .094 1.167l-1.065 3.29a1 1 0 0 0 1.236 1.168l3.413-.998a2 2 0 0 1 1.099.092 10 10 0 1 0-4.777-4.719" />
        </g>
        <g id="i-repeat-2">
          <path d="m2 9 3-3 3 3" />
          <path d="M13 18H7a2 2 0 0 1-2-2V6" />
          <path d="m22 15-3 3-3-3" />
          <path d="M11 6h6a2 2 0 0 1 2 2v10" />
        </g>
        <g id="i-info">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 16v-4" />
          <path d="M12 8h.01" />
        </g>
        <g id="i-file-text">
          <path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z" />
          <path d="M14 2v5a1 1 0 0 0 1 1h5" />
          <path d="M10 9H8" />
          <path d="M16 13H8" />
          <path d="M16 17H8" />
        </g>
        <g id="i-trending-up">
          <path d="M16 7h6v6" />
          <path d="m22 7-8.5 8.5-5-5L2 17" />
        </g>
        <g id="i-trending-down">
          <path d="M16 17h6v-6" />
          <path d="m22 17-8.5-8.5-5 5L2 7" />
        </g>
        <g id="i-minus">
          <path d="M5 12h14" />
        </g>
        <g id="i-plus">
          <path d="M5 12h14" />
          <path d="M12 5v14" />
        </g>
      </defs>
    </svg>
  );
}

/** Значок из набора. Занимает место одной ссылки вместо своих контуров. */
export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg className={`icon ${className ?? ""}`} viewBox="0 0 24 24" aria-hidden="true">
      <use href={`#i-${name}`} />
    </svg>
  );
}
