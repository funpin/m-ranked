"use client"

import * as React from "react"
import { AlertDialog as AlertDialogPrimitive } from "@base-ui/react/alert-dialog"
import {
  AlertDialog as AnimatedAlertDialog,
  AlertDialogBackdrop as AnimatedBackdrop,
  AlertDialogPopup as AnimatedPopup,
  AlertDialogPortal as AnimatedPortal,
  AlertDialogTrigger as AnimatedTrigger,
} from "@/components/animate-ui/primitives/base/alert-dialog"
import { FADE_IN, FADE_SHOWN, PANEL_IN, PANEL_SHOWN, PANEL_SPRING } from "@/lib/motion-presets"
import { cn } from "cn"

import { Button } from "@/components/ui/button"

// Корень, портал, фон и окно — анимированные примитивы animate-ui: окно
// появляется с лёгким переворотом и размытием, фон проявляется. Остальные
// части — прежние, на Base UI.
function AlertDialog(props: React.ComponentProps<typeof AnimatedAlertDialog>) {
  return <AnimatedAlertDialog data-slot="alert-dialog" {...props} />
}

function AlertDialogTrigger(props: React.ComponentProps<typeof AnimatedTrigger>) {
  return <AnimatedTrigger data-slot="alert-dialog-trigger" {...props} />
}

function AlertDialogPortal(props: React.ComponentProps<typeof AnimatedPortal>) {
  return <AnimatedPortal data-slot="alert-dialog-portal" {...props} />
}

function AlertDialogOverlay({ className, ...props }: React.ComponentProps<typeof AnimatedBackdrop>) {
  return (
    <AnimatedBackdrop
      data-slot="alert-dialog-overlay"
      initial={FADE_IN}
      animate={FADE_SHOWN}
      exit={FADE_IN}
      className={cn("fixed inset-0 isolate z-[400] bg-black/70 supports-backdrop-filter:backdrop-blur-xs", className)}
      {...props}
    />
  )
}

function AlertDialogContent({
  className,
  size = "default",
  ...props
}: React.ComponentProps<typeof AnimatedPopup> & {
  size?: "default" | "sm"
}) {
  return (
    <AlertDialogPortal>
      <AlertDialogOverlay />
      <AnimatedPopup
        data-slot="alert-dialog-content"
        data-size={size}
        initial={PANEL_IN}
        animate={PANEL_SHOWN}
        exit={PANEL_IN}
        transition={PANEL_SPRING}
        className={cn(
          "group/alert-dialog-content fixed inset-0 z-[400] m-auto grid h-fit w-[calc(100%-2rem)] gap-3 rounded-xl bg-popover p-4 text-popover-foreground ring-1 ring-foreground/10 outline-none data-[size=default]:max-w-xs data-[size=sm]:max-w-64 data-[size=default]:sm:max-w-sm",
          className
        )}
        {...props}
      />
    </AlertDialogPortal>
  )
}

function AlertDialogHeader({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-dialog-header"
      className={cn(
        "grid grid-rows-[auto_1fr] place-items-center gap-1 text-center has-data-[slot=alert-dialog-media]:grid-rows-[auto_auto_1fr] has-data-[slot=alert-dialog-media]:gap-x-4 sm:group-data-[size=default]/alert-dialog-content:place-items-start sm:group-data-[size=default]/alert-dialog-content:text-left sm:group-data-[size=default]/alert-dialog-content:has-data-[slot=alert-dialog-media]:grid-rows-[auto_1fr]",
        className
      )}
      {...props}
    />
  )
}

function AlertDialogFooter({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-dialog-footer"
      className={cn(
        "flex flex-col-reverse gap-2 group-data-[size=sm]/alert-dialog-content:grid group-data-[size=sm]/alert-dialog-content:grid-cols-2 sm:flex-row sm:justify-end",
        className
      )}
      {...props}
    />
  )
}

function AlertDialogMedia({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-dialog-media"
      className={cn(
        "mb-2 inline-flex size-8 items-center justify-center rounded-md bg-muted sm:group-data-[size=default]/alert-dialog-content:row-span-2 *:[svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    />
  )
}

function AlertDialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Title>) {
  return (
    <AlertDialogPrimitive.Title
      data-slot="alert-dialog-title"
      className={cn(
        "font-heading text-sm font-medium sm:group-data-[size=default]/alert-dialog-content:group-has-data-[slot=alert-dialog-media]/alert-dialog-content:col-start-2",
        className
      )}
      {...props}
    />
  )
}

function AlertDialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Description>) {
  return (
    <AlertDialogPrimitive.Description
      data-slot="alert-dialog-description"
      className={cn(
        "text-xs/relaxed text-balance text-muted-foreground md:text-pretty *:[a]:underline *:[a]:underline-offset-3 *:[a]:hover:text-foreground",
        className
      )}
      {...props}
    />
  )
}

function AlertDialogAction({
  className,
  ...props
}: React.ComponentProps<typeof Button>) {
  return (
    <Button
      data-slot="alert-dialog-action"
      className={cn(className)}
      {...props}
    />
  )
}

function AlertDialogCancel({
  className,
  variant = "outline",
  size = "default",
  ...props
}: AlertDialogPrimitive.Close.Props &
  Pick<React.ComponentProps<typeof Button>, "variant" | "size">) {
  return (
    <AlertDialogPrimitive.Close
      data-slot="alert-dialog-cancel"
      className={cn(className)}
      render={<Button variant={variant} size={size} />}
      {...props}
    />
  )
}

export {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogOverlay,
  AlertDialogPortal,
  AlertDialogTitle,
  AlertDialogTrigger,
}
