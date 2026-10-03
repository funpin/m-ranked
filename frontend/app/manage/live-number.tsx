"use client";

import { SlidingNumber } from "@/components/animate-ui/primitives/texts/sliding-number";

/** Число, которое при обновлении данных перекатывается к новому значению
 *  (SlidingNumber из animate-ui); при первой отрисовке — сразу на месте. */
export function LiveNumber({ value, decimals = 0, suffix, className }: {
  value: number; decimals?: number; suffix?: string; className?: string;
}) {
  return (
    <span className={className}>
      <span className="sr-only">{value.toLocaleString("ru-RU", { maximumFractionDigits: decimals })}{suffix}</span>
      <span aria-hidden="true" className="inline-flex items-baseline tabular-nums">
        <SlidingNumber number={value} decimalPlaces={decimals} decimalSeparator="," thousandSeparator=" " initiallyStable />
        {suffix}
      </span>
    </span>
  );
}
