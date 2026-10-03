"use client"

import type * as React from "react"
import {
  TooltipArrow as TooltipArrowPrimitive,
  TooltipPopup as TooltipPopupPrimitive,
  TooltipPortal as TooltipPortalPrimitive,
  TooltipPositioner as TooltipPositionerPrimitive,
  TooltipProvider as TooltipProviderPrimitive,
  Tooltip as TooltipPrimitive,
  TooltipTrigger as TooltipTriggerPrimitive,
} from "@/components/animate-ui/primitives/base/tooltip"
import { POP_IN, POP_SHOWN, POP_SPRING } from "@/lib/motion-presets"
import { cn } from "cn"

// Подсказки — анимированные примитивы animate-ui поверх Base UI: появление и
// исчезновение пружиной вместо CSS-ключевых кадров. Внешний вид и API те же.

function TooltipProvider({ delay = 0, ...props }: React.ComponentProps<typeof TooltipProviderPrimitive>) {
  return <TooltipProviderPrimitive data-slot="tooltip-provider" delay={delay} {...props} />
}

function Tooltip(props: React.ComponentProps<typeof TooltipPrimitive>) {
  return <TooltipPrimitive {...props} />
}

function TooltipTrigger(props: React.ComponentProps<typeof TooltipTriggerPrimitive>) {
  return <TooltipTriggerPrimitive {...props} />
}

function TooltipContent({
  className,
  side = "top",
  sideOffset = 6,
  align = "center",
  alignOffset = 0,
  children,
  ...props
}: React.ComponentProps<typeof TooltipPopupPrimitive> &
  Pick<React.ComponentProps<typeof TooltipPositionerPrimitive>, "align" | "alignOffset" | "side" | "sideOffset">) {
  return (
    <TooltipPortalPrimitive>
      <TooltipPositionerPrimitive align={align} alignOffset={alignOffset} side={side} sideOffset={sideOffset} className="isolate z-[410]">
        <TooltipPopupPrimitive
          data-slot="tooltip-content"
          initial={POP_IN}
          animate={POP_SHOWN}
          exit={POP_IN}
          transition={POP_SPRING}
          className={cn(
            "z-50 inline-flex w-fit max-w-xs origin-(--transform-origin) items-center gap-1.5 rounded-lg bg-popover px-3 py-2 text-xs leading-relaxed text-popover-foreground shadow-md ring-1 ring-foreground/10 has-data-[slot=kbd]:pr-1.5",
            className
          )}
          {...props}
        >
          {children}
          <TooltipArrowPrimitive className="pointer-events-none z-50 size-2.5 translate-y-[calc(-50%-2px)] rotate-45 rounded-[2px] bg-popover fill-popover data-[side=bottom]:top-1 data-[side=left]:top-1/2! data-[side=left]:-right-1 data-[side=left]:-translate-y-1/2 data-[side=right]:top-1/2! data-[side=right]:-left-1 data-[side=right]:-translate-y-1/2 data-[side=top]:-bottom-2.5" />
        </TooltipPopupPrimitive>
      </TooltipPositionerPrimitive>
    </TooltipPortalPrimitive>
  )
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider }
