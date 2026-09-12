"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { applyTheme, type ResolvedTheme, type ThemePreference } from "@/lib/theme";

/**
 * The menu half of the theme control. It is loaded on demand, because the
 * floating-menu primitive is around 48 KiB gzip and the header sits in the
 * root layout, so it would otherwise land in the first load of every route.
 */
export function ThemeMenu({ preference, resolved, label, defaultOpen }: {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  label: string;
  defaultOpen?: boolean;
}) {
  return (
    <DropdownMenu defaultOpen={defaultOpen}>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" size="icon" aria-label={label} title={label}>
            {preference === "system"
              ? <Monitor className="size-[1.15rem]" aria-hidden="true" />
              : resolved === "dark"
                ? <Moon className="size-[1.15rem]" aria-hidden="true" />
                : <Sun className="size-[1.15rem]" aria-hidden="true" />}
          </Button>
        }
      />
      <DropdownMenuContent align="end" className="min-w-[9rem]">
        <DropdownMenuRadioGroup value={preference} onValueChange={(value) => applyTheme(value as ThemePreference)}>
          <DropdownMenuRadioItem value="light">
            <Sun className="size-4" aria-hidden="true" />
            Светлая
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <Moon className="size-4" aria-hidden="true" />
            Тёмная
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">
            <Monitor className="size-4" aria-hidden="true" />
            Системная
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
