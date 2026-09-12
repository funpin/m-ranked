"use client";

import { useMemo, useSyncExternalStore } from "react";
type Key = "reactions" | "views" | "comments" | "shares";
type Scale = "shared" | "auto";
const volatile = new Map<string,string>();
const changed = "m-ranked:history-preferences";
function subscribe(notify: () => void) {
  window.addEventListener("storage",notify);window.addEventListener(changed,notify);
  return () => {window.removeEventListener("storage",notify);window.removeEventListener(changed,notify);};
}

export function useHistoryPreferences(platform: string, delta: boolean, keys: Key[]) {
  const storageKey = platform === "telegram" ? "m-ranked:post-chart-preferences:v1" : `m-ranked:platform-post-chart-preferences:v1:${platform}`;
  const serialized = useSyncExternalStore(subscribe,() => {try{return volatile.get(storageKey) ?? localStorage.getItem(storageKey) ?? "";}catch{return volatile.get(storageKey) ?? "";}},() => "");
  const parsed = useMemo(() => {try{const value=JSON.parse(serialized);return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string,unknown> : {};}catch{return {};}},[serialized]);
  const hidden = useMemo(() => new Set(keys.filter((key,index) => {
    const values = parsed[delta ? "deltaVisible" : "totalVisible"];
    const flag = platform === "telegram" ? parsed[delta ? `delta${key[0]!.toUpperCase()}${key.slice(1)}` : key]
      : values && typeof values === "object" ? (values as Record<string,unknown>)[key] : undefined;
    return typeof flag === "boolean" ? !flag : index !== 0;
  })),[parsed,keys,delta,platform]);
  const scale: Scale = parsed[delta ? "deltaScaleMode" : "scaleMode"] === "auto" ? "auto" : "shared";
  function save(nextHidden: Set<Key>,nextScale: Scale) {
    const value = {...parsed,[delta ? "deltaScaleMode" : "scaleMode"]:nextScale};
    if(platform === "telegram") keys.forEach((key) => {value[delta ? `delta${key[0]!.toUpperCase()}${key.slice(1)}` : key] = !nextHidden.has(key);});
    else value[delta ? "deltaVisible" : "totalVisible"] = Object.fromEntries(keys.map((key) => [key,!nextHidden.has(key)]));
    try {localStorage.setItem(storageKey,JSON.stringify(value));}catch {volatile.set(storageKey,JSON.stringify(value));}
    window.dispatchEvent(new Event(changed));
  }
  return {hidden,scale,setHidden:(update:(old:Set<Key>)=>Set<Key>)=>save(update(hidden),scale),setScale:(value:Scale)=>save(hidden,value)};
}
