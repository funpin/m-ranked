import { CircleAlert, CircleCheck, CircleDashed, OctagonAlert, TriangleAlert, type LucideIcon, type LucideProps } from "lucide-react";

// Значок уровня — отдельный модуль: таблицы постов (страница аккаунта)
// показывают только уровень, и значки всех паттернов им не нужны.
const LEVEL_ICONS: Readonly<Record<number, LucideIcon>> = {
  0: CircleCheck, 1: CircleAlert, 2: TriangleAlert, 3: OctagonAlert,
};

/** null — пост ещё не проанализирован. */
export function LevelIcon({ level, ...props }: { level: number | null } & LucideProps) {
  const Icon = level === null ? CircleDashed : LEVEL_ICONS[level] ?? CircleAlert;
  return <Icon aria-hidden="true" {...props} />;
}
