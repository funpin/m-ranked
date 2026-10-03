"use client"

import * as React from "react"
import { type VariantProps } from "class-variance-authority"
import {
  Toggle as TogglePrimitive,
  ToggleGroupHighlight,
  ToggleGroup as ToggleGroupPrimitive,
  ToggleHighlight,
  useToggleGroup,
} from "@/components/animate-ui/primitives/base/toggle-group"
import { cn } from "cn"

import { toggleVariants } from "@/components/ui/toggle"

// Группа переключателей animate-ui: подложка выбранного пункта переезжает
// пружиной, а не перекрашивает кнопки мгновенно. Выбор, клавиатура и
// aria-pressed — от Base UI; API прежний (variant, size, spacing).

const ToggleGroupContext = React.createContext<VariantProps<typeof toggleVariants>>({
  size: "default",
  variant: "default",
})

const HIGHLIGHT_SPRING = { type: "spring", stiffness: 420, damping: 36 } as const

function ToggleGroup({
  className,
  variant,
  size,
  orientation = "horizontal",
  children,
  ...rest
}: React.ComponentProps<typeof ToggleGroupPrimitive> &
  VariantProps<typeof toggleVariants> & {
    /** Прежний API задавал зазор между кнопками; у сегментного вида он
     *  постоянный, параметр принимается ради совместимости. */
    spacing?: number
    orientation?: "horizontal" | "vertical"
  }) {
  const { spacing, ...props } = rest
  void spacing
  return (
    <ToggleGroupPrimitive
      data-slot="toggle-group"
      data-variant={variant}
      data-size={size}
      data-orientation={orientation}
      orientation={orientation}
      className={cn(
        "group/toggle-group relative flex w-fit flex-row items-center gap-0.5 rounded-lg data-[variant=outline]:border data-[variant=outline]:border-input data-[variant=outline]:p-0.5 data-[orientation=vertical]:flex-col data-[orientation=vertical]:items-stretch",
        className
      )}
      {...props}
    >
      <ToggleGroupContext.Provider value={{ variant, size }}>
        {props.multiple ? children : (
          <ToggleGroupHighlight transition={HIGHLIGHT_SPRING}
            className="rounded-md bg-muted shadow-xs ring-1 ring-foreground/10 dark:bg-input/50">
            {children}
          </ToggleGroupHighlight>
        )}
      </ToggleGroupContext.Provider>
    </ToggleGroupPrimitive>
  )
}

function ToggleGroupItem({
  className,
  children,
  variant = "default",
  size = "default",
  ...props
}: React.ComponentProps<typeof TogglePrimitive> & VariantProps<typeof toggleVariants>) {
  const context = React.useContext(ToggleGroupContext)
  const { multiple } = useToggleGroup()
  return (
    <ToggleHighlight value={props.value?.toString()} className={cn(multiple && "rounded-md bg-muted")}>
      <TogglePrimitive
        data-slot="toggle-group-item"
        data-variant={context.variant || variant}
        data-size={context.size || size}
        className={cn(
          toggleVariants({ variant: context.variant || variant, size: context.size || size }),
          // Цвет выбранного пункта рисует подложка; сама кнопка прозрачна.
          "relative z-[1] min-w-0 shrink-0 border-0 bg-transparent shadow-none hover:bg-transparent aria-pressed:bg-transparent aria-pressed:text-foreground data-[state=on]:bg-transparent text-muted-foreground hover:text-foreground focus:z-10 focus-visible:z-10",
          className
        )}
        {...props}
      >
        {children}
      </TogglePrimitive>
    </ToggleHighlight>
  )
}

export { ToggleGroup, ToggleGroupItem }
