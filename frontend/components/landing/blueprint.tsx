import type { ReactNode } from "react";

/** Полоса раздела в духе чертежа: «01 / Площадки» слева, пояснение справа,
 *  тонкие линии сверху и снизу и крестик на пересечении с рамкой. */
export function SectionBar({ index, label, meta, metaStart = false }: {
  index: number; label: string; meta?: ReactNode;
  /** Пояснение сразу за названием, а не у правого края: на широком экране
   *  правый верхний угол первого экрана занимает оглавление. */
  metaStart?: boolean;
}) {
  return (
    <div className={metaStart ? "landing-bar landing-bar--start" : "landing-bar"} aria-hidden="true">
      <span className="landing-bar-cross" />
      <span className="landing-mono"><span className="text-muted-foreground">{String(index).padStart(2, "0")} /</span> {label}</span>
      {meta ? <span className="landing-mono text-muted-foreground hidden truncate sm:block">{meta}</span> : null}
    </div>
  );
}

/** Номер ячейки — цветной квадрат с моноширинными цифрами. */
export function CellNumber({ value, tone = "var(--landing-accent)" }: { value: number; tone?: string }) {
  return <span className="landing-cell-number" style={{ background: tone }}>{String(value).padStart(2, "0")}</span>;
}
