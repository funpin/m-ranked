import { CalendarDays, Eye, Heart } from "lucide-react";
import Link from "@/components/native-link";
import { Glyphs, WeightStrip } from "@/components/rating/formula-visual";
import type { RatingForecast } from "@/lib/types";

/** Формула М-Рейтинга картинкой — перед таблицей, как на других вкладках «Рейтинга». */
export function ForecastMethod({ forecast }: { forecast: RatingForecast }) {
  const errors = [["Соцсети", forecast.errors.social], ["MAX", forecast.errors.max], ["VK", forecast.errors.vk], ["Rutube", forecast.errors.rutube]] as const;
  return <section aria-labelledby="rating-method" data-testid="rating-method" className="bg-muted/40 mb-6 space-y-5 rounded-lg p-4 sm:p-5">
    <h2 id="rating-method" className="font-heading text-base font-semibold">Как считает М-Рейтинг</h2>
    <WeightStrip weights={{ max: 0.4, vk: 0.3, rutube: 0.3 }} label="Балл соцсетей М-Рейтинга" />
    <div>
      <p className="mb-3 text-sm">Балл VK и MAX — среднее трёх частей; Rutube — меньше 5 видео за месяц дают 0:</p>
      <Glyphs items={[
        { icon: CalendarDays, label: "Постов за месяц" },
        { icon: Eye, label: "Просмотры поста на студента" },
        { icon: Heart, label: "Реакции на просмотр" },
      ]} />
    </div>
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span>Типичная ошибка балла:</span>
      {errors.map(([label, value]) => <span key={label} className="bg-background ring-border rounded-md px-2 py-0.5 tabular-nums ring-1">
        {label} ±{value}</span>)}
      <span className="text-muted-foreground text-xs">Формула, версия {forecast.formulaVersion};{" "}
        <Link href="/methodology/rating-forecast" className="underline">методика</Link></span>
    </div>
  </section>;
}
