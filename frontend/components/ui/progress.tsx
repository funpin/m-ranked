"use client"

import type * as React from "react"
import { Progress as ProgressPrimitive } from "@base-ui/react/progress"
import * as m from "motion/react-m"
import { createContext, useContext } from "react"
import { cn } from "cn"

// Полоса в манере animate-ui (primitives-base-progress): заполнение доезжает
// до значения пружиной. Счётчик значения из оригинала не нужен и не грузится.
const FILL_SPRING = { type: "spring", stiffness: 120, damping: 26 } as const
const ProgressValueContext = createContext(0)
const AnimatedIndicator = m.create(ProgressPrimitive.Indicator)

function AnimatedProgress(props: ProgressPrimitive.Root.Props) {
  return (
    <ProgressValueContext.Provider value={props.value ?? 0}>
      <ProgressPrimitive.Root {...props} />
    </ProgressValueContext.Provider>
  )
}

function Progress({
  className,
  children,
  value,
  ...props
}: ProgressPrimitive.Root.Props) {
  return (
    <AnimatedProgress
      value={value}
      data-slot="progress"
      className={cn("flex flex-wrap gap-3", className)}
      {...props}
    >
      {children}
      <ProgressTrack>
        <ProgressIndicator />
      </ProgressTrack>
    </AnimatedProgress>
  )
}

function ProgressTrack({ className, ...props }: ProgressPrimitive.Track.Props) {
  return (
    <ProgressPrimitive.Track
      className={cn(
        "relative flex h-1 w-full items-center overflow-x-hidden rounded-md bg-muted",
        className
      )}
      data-slot="progress-track"
      {...props}
    />
  )
}

function ProgressIndicator({
  className,
  ...props
}: React.ComponentProps<typeof AnimatedIndicator>) {
  const value = useContext(ProgressValueContext)
  return (
    <AnimatedIndicator
      data-slot="progress-indicator"
      animate={{ width: `${value}%` }}
      transition={FILL_SPRING}
      className={cn("h-full bg-primary", className)}
      {...props}
    />
  )
}

function ProgressLabel({ className, ...props }: ProgressPrimitive.Label.Props) {
  return (
    <ProgressPrimitive.Label
      className={cn("text-xs/relaxed font-medium", className)}
      data-slot="progress-label"
      {...props}
    />
  )
}

function ProgressValue({ className, ...props }: ProgressPrimitive.Value.Props) {
  return (
    <ProgressPrimitive.Value
      className={cn(
        "ml-auto text-xs/relaxed text-muted-foreground tabular-nums",
        className
      )}
      data-slot="progress-value"
      {...props}
    />
  )
}

export {
  Progress,
  ProgressTrack,
  ProgressIndicator,
  ProgressLabel,
  ProgressValue,
}
