"use client"

import * as React from "react"
import {
  PopoverDescription as PopoverDescriptionPrimitive,
  PopoverPopup as PopoverPopupPrimitive,
  PopoverPortal as PopoverPortalPrimitive,
  PopoverPositioner as PopoverPositionerPrimitive,
  Popover as PopoverPrimitive,
  PopoverTitle as PopoverTitlePrimitive,
  PopoverTrigger as PopoverTriggerPrimitive,
} from "@/components/animate-ui/primitives/base/popover"
import { POP_IN, POP_SHOWN, POP_SPRING } from "@/lib/motion-presets"
import { cn } from "cn"

// Анимированный popover animate-ui поверх Base UI; API и вид прежние.

function Popover(props: React.ComponentProps<typeof PopoverPrimitive>) {
  return <PopoverPrimitive {...props} />
}

function PopoverTrigger(props: React.ComponentProps<typeof PopoverTriggerPrimitive>) {
  return <PopoverTriggerPrimitive {...props} />
}

function PopoverContent({
  className,
  align = "center",
  alignOffset = 0,
  side = "bottom",
  sideOffset = 6,
  ...props
}: React.ComponentProps<typeof PopoverPopupPrimitive> &
  Pick<React.ComponentProps<typeof PopoverPositionerPrimitive>, "align" | "alignOffset" | "side" | "sideOffset">) {
  return (
    <PopoverPortalPrimitive>
      <PopoverPositionerPrimitive align={align} alignOffset={alignOffset} side={side} sideOffset={sideOffset} className="isolate z-[410]">
        <PopoverPopupPrimitive
          data-slot="popover-content"
          initial={POP_IN}
          animate={POP_SHOWN}
          exit={POP_IN}
          transition={POP_SPRING}
          className={cn(
            "z-50 flex w-72 origin-(--transform-origin) flex-col gap-4 rounded-lg bg-popover p-2.5 text-xs text-popover-foreground shadow-md ring-1 ring-foreground/10 outline-hidden",
            className
          )}
          {...props}
        />
      </PopoverPositionerPrimitive>
    </PopoverPortalPrimitive>
  )
}

function PopoverHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="popover-header" className={cn("flex flex-col gap-1 text-xs", className)} {...props} />
}

function PopoverTitle({ className, ...props }: React.ComponentProps<typeof PopoverTitlePrimitive>) {
  return <PopoverTitlePrimitive data-slot="popover-title" className={cn("text-sm font-medium", className)} {...props} />
}

function PopoverDescription({ className, ...props }: React.ComponentProps<typeof PopoverDescriptionPrimitive>) {
  return <PopoverDescriptionPrimitive data-slot="popover-description" className={cn("text-muted-foreground", className)} {...props} />
}

export {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
}
