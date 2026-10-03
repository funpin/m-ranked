"use client"

import * as React from "react"
import { XIcon } from "lucide-react"
import {
  DialogBackdrop as DialogBackdropPrimitive,
  DialogClose as DialogClosePrimitive,
  DialogDescription as DialogDescriptionPrimitive,
  DialogPopup as DialogPopupPrimitive,
  DialogPortal as DialogPortalPrimitive,
  Dialog as DialogPrimitive,
  DialogTitle as DialogTitlePrimitive,
  DialogTrigger as DialogTriggerPrimitive,
} from "@/components/animate-ui/primitives/base/dialog"
import { FADE_IN, FADE_SHOWN, PANEL_IN, PANEL_SHOWN, PANEL_SPRING } from "@/lib/motion-presets"
import { cn } from "cn"

// Модальное окно animate-ui на Base UI в разметке shadcn: фон проявляется,
// окно разворачивается с размытием. Фокус, Escape и блокировку прокрутки
// даёт Base UI.

function Dialog(props: React.ComponentProps<typeof DialogPrimitive>) {
  return <DialogPrimitive data-slot="dialog" {...props} />
}

function DialogTrigger(props: React.ComponentProps<typeof DialogTriggerPrimitive>) {
  return <DialogTriggerPrimitive data-slot="dialog-trigger" {...props} />
}

function DialogClose(props: React.ComponentProps<typeof DialogClosePrimitive>) {
  return <DialogClosePrimitive data-slot="dialog-close" {...props} />
}

function DialogContent({
  className,
  children,
  showCloseButton = true,
  ...props
}: React.ComponentProps<typeof DialogPopupPrimitive> & { showCloseButton?: boolean }) {
  return (
    <DialogPortalPrimitive>
      <DialogBackdropPrimitive data-slot="dialog-overlay" initial={FADE_IN} animate={FADE_SHOWN} exit={FADE_IN} className="fixed inset-0 isolate z-[400] bg-black/70 supports-backdrop-filter:backdrop-blur-xs" />
      {/* Центр — через inset-0 и m-auto, а не translate(-50%): при нечётной
          высоте окна сдвиг на половину ставил его на полпикселя, и текст мылился. */}
      <DialogPopupPrimitive
        data-slot="dialog-content"
        initial={PANEL_IN}
        animate={PANEL_SHOWN}
        exit={PANEL_IN}
        transition={PANEL_SPRING}
        className={cn(
          "fixed inset-0 z-[400] m-auto grid h-fit max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg gap-4 overflow-y-auto rounded-xl bg-popover p-5 text-sm text-popover-foreground shadow-lg ring-1 ring-foreground/10 outline-none",
          className
        )}
        {...props}
      >
        {children}
        {showCloseButton ? (
          <DialogClosePrimitive
            data-slot="dialog-close"
            className="absolute top-3 right-3 inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            <XIcon className="size-4" aria-hidden="true" />
            <span className="sr-only">Закрыть</span>
          </DialogClosePrimitive>
        ) : null}
      </DialogPopupPrimitive>
    </DialogPortalPrimitive>
  )
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="dialog-header" className={cn("grid gap-1.5 pr-8", className)} {...props} />
}

function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="dialog-footer" className={cn("flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)} {...props} />
}

function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogTitlePrimitive>) {
  return <DialogTitlePrimitive data-slot="dialog-title" className={cn("font-heading text-base font-semibold", className)} {...props} />
}

function DialogDescription({ className, ...props }: React.ComponentProps<typeof DialogDescriptionPrimitive>) {
  return <DialogDescriptionPrimitive data-slot="dialog-description" className={cn("text-xs/relaxed text-muted-foreground", className)} {...props} />
}

export { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger }
