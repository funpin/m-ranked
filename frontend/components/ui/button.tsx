"use client"

import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { type VariantProps } from "class-variance-authority"
import * as m from "motion/react-m";
import { cn } from "cn"
import { buttonVariants } from "./button-variants"


// Нажатие — короткая пружина animate-ui (m.button). Кнопки, которые рисуют
// свой элемент через render (ссылки в облике кнопки), остаются как есть.
const PRESS = { scale: 0.97 } as const
const PRESS_SPRING = { type: "spring", stiffness: 520, damping: 30 } as const

function Button({
  className,
  variant = "default",
  size = "default",
  render,
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      render={render ?? <m.button whileTap={props.disabled ? undefined : PRESS} transition={PRESS_SPRING} />}
      {...props}
    />
  )
}

export { Button }
