"use client";

import { useEffect, useRef, useState } from "react";

/** Keep the avatar slot usable if a refreshed file is missing or cannot decode. */
export function ContributorAvatar({ src, fallback, login }: { src: string; fallback?: string; login: string }) {
  const [failed, setFailed] = useState<string[]>([]);
  const image = useRef<HTMLImageElement>(null);
  const current = failed.includes(src) ? fallback : src;
  useEffect(() => {
    // An image can fail before React hydrates and attaches onError. Check its
    // already completed result too, so SSR never leaves a broken image behind.
    const frame = requestAnimationFrame(() => {
      if (current && image.current?.complete && image.current.naturalWidth === 0) {
        setFailed(previous => previous.includes(current) ? previous : [...previous,current]);
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [current]);
  if (!current || failed.includes(current)) return <span aria-hidden="true"
    className="ring-background bg-muted text-muted-foreground grid size-6 place-items-center rounded-full text-[10px] font-semibold ring-2">
    {login.slice(0,2).toUpperCase()}
  </span>;
  // eslint-disable-next-line @next/next/no-img-element
  return <img ref={image} src={current} alt="" width={24} height={24} decoding="async"
    onError={() => setFailed(previous => previous.includes(current) ? previous : [...previous,current])}
    className="ring-background bg-muted block size-6 rounded-full object-cover ring-2" />;
}
