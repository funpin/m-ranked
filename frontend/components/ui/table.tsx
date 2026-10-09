"use client"

import * as React from "react"
import { cn } from "cn"

/**
 * Таблица в духе data-table shadcn: своя рамка со скруглением, приглушённая
 * шапка, ровные отступы ячеек. Один вид для всех таблиц сайта; frame={false}
 * снимает рамку, когда её уже даёт обёртка (например, прокрутка со
 * sticky-шапкой).
 */
function Table({ className, containerProps, frame = true, ...props }: React.ComponentProps<"table"> & {
  containerProps?: React.ComponentProps<"div">
  frame?: boolean
}) {
  return (
    <div
      data-slot="table-container"
      data-frame={frame || undefined}
      {...containerProps}
      className={cn(
        "relative w-full overflow-x-auto",
        frame && "rounded-lg border bg-card",
        containerProps?.className
      )}
    >
      <table
        data-slot="table"
        className={cn("w-full caption-bottom text-[0.8125rem]", className)}
        {...props}
      />
    </div>
  )
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn("bg-muted/60 [&_tr]:border-b [&_tr]:hover:bg-transparent", className)}
      {...props}
    />
  )
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  )
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn(
        "border-t bg-muted/50 font-medium [&>tr]:last:border-b-0",
        className
      )}
      {...props}
    />
  )
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b transition-colors hover:bg-muted/40 has-aria-expanded:bg-muted/50 data-[state=selected]:bg-muted/70",
        className
      )}
      {...props}
    />
  )
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "h-10 px-3 text-left align-middle text-xs font-medium whitespace-nowrap text-foreground [&:has([role=checkbox])]:pr-0",
        className
      )}
      {...props}
    />
  )
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "px-3 py-2.5 align-middle whitespace-nowrap [&:has([role=checkbox])]:pr-0",
        className
      )}
      {...props}
    />
  )
}

function TableCaption({
  className,
  ...props
}: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-4 text-xs text-muted-foreground", className)}
      {...props}
    />
  )
}

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
}
