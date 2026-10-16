"use client";

import dynamic from "next/dynamic";

// Разброс «прогноз против факта» нужен только опубликованному месяцу и стоит
// под таблицей: recharts не идёт в первую загрузку вкладки (бюджет 205 КиБ).
const loading = () => <div className="bg-muted/60 mt-8 aspect-square w-full max-w-[440px] rounded-md" aria-hidden="true" />;

export const ForecastScatter = dynamic(() => import("@/components/rating/forecast-scatter").then((module) => module.ForecastScatter), { ssr: false, loading });
