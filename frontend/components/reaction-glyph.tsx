"use client";

import { useState } from "react";

/** Реакция как глиф: эмодзи текстом, пользовательская — картинкой через
 *  прокси /emoji, неизвестная — «❔». Ошибка картинки остаётся видимой. */
export function ReactionGlyph({ name, className = "size-5" }: { name: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (name.startsWith("custom:") && /^\d+$/.test(name.slice(7)) && !failed) {
    // Same-origin proxy validates image type; failure remains visible and accessible.
    // eslint-disable-next-line @next/next/no-img-element
    return <img className={`inline-block object-contain align-middle ${className}`} src={`/emoji/${name.slice(7)}`} alt="Пользовательская реакция" loading="lazy" onError={() => setFailed(true)} />;
  }
  return <>{name.startsWith("custom:") || name.startsWith("unknown:") ? "❔" : name === "paid:star" ? "⭐" : name}</>;
}
