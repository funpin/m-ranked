import Link from "@/components/native-link";
import type { RatingForecast } from "@/lib/types";

export function ForecastMethod({ forecast }: { forecast: RatingForecast }) {
  return <section aria-labelledby="rating-method" className="bg-muted/40 mt-8 rounded-lg p-4 text-sm">
    <h2 id="rating-method" className="font-heading mb-2 text-base font-semibold">Как считается прогноз</h2>
    <p>Соцсети = 0.4 · MAX + 0.3 · VK + 0.3 · Rutube. Балл VK и MAX — среднее трёх шкал: число публикаций за месяц,
      средние просмотры публикации на одного студента и вовлечённость (реакции, комментарии и репосты к просмотрам).
      Rutube: меньше 5 видео — 0. Места — среди всех вузов официального рейтинга; вузы, которых мы не отслеживаем,
      стоят с баллами за {forecast.basePeriod.toLowerCase()}.</p>
    <p className="mt-2">Типичная ошибка балла: соцсети ±{forecast.errors.social}, MAX ±{forecast.errors.max},
      VK ±{forecast.errors.vk}, Rutube ±{forecast.errors.rutube}; в скобках — места при такой ошибке.
      СМИ, сайт и повестка МОН не прогнозируются. Формула, версия {forecast.formulaVersion}.</p>
    <p className="mt-2"><Link href="/methodology/rating-forecast" className="underline">Методика и ограничения</Link></p>
  </section>;
}
