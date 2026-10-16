import type { Metadata } from "next";
import { RatingTabs } from "@/components/rating/rating-tabs";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Рейтинг: наш рейтинг",
  description: "Собственный рейтинг вузов по соцсетям — методика в разработке.",
};

export default async function OwnRatingPage() {
  let own;
  try { own = await api.ownRating(); } catch { return <ApiFailureState retryHref="/rating/own" />; }
  return <>
    <PageHeader title="Рейтинг" description="Собственный вариант расчёта по нашим данным отслеживания." />
    <RatingTabs active="/rating/own" />
    <section aria-labelledby="own-method" className="bg-muted/40 rounded-lg p-4 text-sm">
      <h2 id="own-method" className="font-heading mb-2 text-base font-semibold">Методика в разработке</h2>
      <p className="mb-2">Здесь появится наш рейтинг, когда будет выбрана методика. Открытые вопросы:</p>
      <ul className="list-disc pl-5">{own.questions.map((question) => <li key={question}>{question}</li>)}</ul>
    </section>
    <div className="mt-6 overflow-x-auto" aria-hidden="true">
      <table className="text-muted-foreground w-full min-w-[480px] text-sm">
        <thead><tr className="text-left text-xs"><th className="py-2">Место</th><th className="py-2">Вуз</th><th className="py-2 text-right">Балл</th></tr></thead>
        <tbody><tr className="border-t"><td className="py-6 text-center" colSpan={3}>Таблица появится вместе с методикой</td></tr></tbody>
      </table>
    </div>
  </>;
}
