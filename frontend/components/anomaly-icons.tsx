import {
  ArrowDownToLine, ChartNoAxesColumnDecreasing, ChartNoAxesCombined, TrendingUp, ArrowDownUp, ArrowUpToLine, ChevronsUp,
  CircleAlert, Ellipsis, FastForward, History, Layers, MoveUpRight, Package,
  Percent, Zap, type LucideIcon, type LucideProps,
} from "lucide-react";

export { LevelIcon } from "@/components/anomaly-level-icon";

/** Значки признаков и уровней — из набора lucide, общего с остальным
 *  интерфейсом. Символы, которые пишет анализ, остаются в ответе API для
 *  других клиентов, но экран рисует только эти значки. */
const PATTERN_ICONS: Readonly<Record<number, LucideIcon>> = {
  1: MoveUpRight, 2: Zap, 4: Ellipsis, 5: FastForward, 6: ArrowDownUp,
  7: ChevronsUp, 8: Layers, 9: ArrowUpToLine, 10: Percent, 11: ChartNoAxesCombined, 12: TrendingUp,
  13: History, 14: Package, 15: ArrowDownToLine, 16: ChartNoAxesColumnDecreasing,
};

export function PatternIcon({ pattern, ...props }: { pattern: number } & LucideProps) {
  const Icon = PATTERN_ICONS[pattern] ?? CircleAlert;
  return <Icon aria-hidden="true" {...props} />;
}

