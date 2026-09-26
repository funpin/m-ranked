"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

/** Копирует пример запроса; без скрипта пример просто выделяется вручную. */
export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button type="button" aria-label={copied ? "Скопировано" : "Скопировать запрос"}
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1600);
        });
      }}
      className="text-muted-foreground hover:text-foreground hover:bg-muted focus-visible:ring-ring/60 grid size-8 shrink-0 place-items-center rounded-md outline-none focus-visible:ring-2">
      {copied ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}
    </button>
  );
}
