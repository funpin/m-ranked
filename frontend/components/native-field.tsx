import type { ComponentProps, ReactNode } from "react";
import { buttonVariants } from "@/components/ui/button";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Native form controls dressed as shadcn ones.
 *
 * The filter forms submit by GET and depend on the browser restoring their
 * controls on back and forward navigation, and the admin forms post with CSRF
 * and row versions in hidden fields. A portal-rendered listbox cannot be
 * driven by form.reset() or by assigning to checked, so these screens keep the
 * real elements and take only the appearance from the design system.
 */

const CONTROL = "border-input dark:bg-input/30 h-9 w-full rounded-md border bg-transparent px-3 py-1 text-sm shadow-xs transition-[color,box-shadow] outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50";

export function NativeSelect({ className, children, ...props }: ComponentProps<"select">) {
  return (
    <span className="relative inline-grid w-full">
      <select className={cn(CONTROL, "appearance-none pr-8", className)} {...props}>
        {children}
      </select>
      <ChevronDown className="text-muted-foreground pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2" aria-hidden="true" />
    </span>
  );
}

export function NativeInput({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(CONTROL, "placeholder:text-muted-foreground", className)} {...props} />;
}

export function Field({ label, hint, className, children }: {
  label: ReactNode; hint?: string; className?: string; children: ReactNode;
}) {
  return (
    <label className={cn("grid gap-1.5 text-sm", className)}>
      <span className={cn("text-muted-foreground font-medium", hint && "cursor-help")} title={hint}>{label}</span>
      {children}
    </label>
  );
}

/**
 * A segmented control built from real radio inputs, so the form still submits
 * and restores it natively while it reads as the design system's toggle group.
 */
export function NativeSegments({ name, options, value, legend }: {
  name: string;
  legend: string;
  value: string;
  options: readonly { value: string; label: string }[];
}) {
  return (
    <fieldset className="m-0 grid gap-1.5 border-0 p-0">
      <legend className="sr-only">{legend}</legend>
      <span className="text-muted-foreground text-sm font-medium" aria-hidden="true">{legend}</span>
      <div data-testid="platform-segments" className="bg-muted flex w-fit rounded-md p-0.5">
        {options.map((option) => (
          <label key={option.value} className="relative m-0 cursor-pointer">
            <input type="radio" name={name} value={option.value} defaultChecked={option.value === value} className="peer absolute opacity-0" />
            <span className="text-muted-foreground peer-checked:bg-background peer-checked:text-foreground peer-focus-visible:ring-ring/50 grid h-8 min-w-12 place-items-center rounded-[calc(var(--radius)-4px)] px-3 text-xs font-bold whitespace-nowrap transition-colors peer-checked:shadow-sm peer-focus-visible:ring-[3px]">
              {option.label}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** Keeps native submit, validation and disabled behavior, including without JS. */
export function NativeButton({ className, variant = "default", ...props }: ComponentProps<"button"> & { variant?: "default" | "outline" | "destructive" }) {
  return <button className={cn(buttonVariants({ variant }), "min-h-9 px-3", className)} {...props} />;
}
