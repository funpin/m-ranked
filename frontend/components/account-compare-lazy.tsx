"use client";

import dynamic from "next/dynamic";

// Место среди вузов и время публикаций стоят в ленте аккаунта не первыми и
// грузят данные только у края экрана; вместе с тепловой картой и расчётами
// сравнения они не идут в первую загрузку страницы (бюджет 205 КиБ).
const loading = () => <div className="bg-muted/60 h-64 w-full rounded-md" aria-hidden="true" />;

export const AccountStanding = dynamic(() => import("@/components/account-compare").then((module) => module.AccountStanding), { ssr: false, loading });
export const AccountTiming = dynamic(() => import("@/components/account-compare").then((module) => module.AccountTiming), { ssr: false, loading });
