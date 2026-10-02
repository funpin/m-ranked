import { CalendarDays, GraduationCap, ExternalLink } from "lucide-react";
import { SummaryTile } from "@/components/summary-tile";
import { trackingDate, studentCount, compactTrackingDate } from "@/lib/institution-profile";
import type { components } from "../../contracts/openapi/m-ranked-v1-client";

type Profile = components["schemas"]["InstitutionProfile"];

export function InstitutionFacts({ profile }: { profile?: Profile }) {
  const added = compactTrackingDate(profile?.trackingStartedAt);
  const students = profile?.students;
  const source = students && /^https:\/\//.test(students.sourceUrl) ? students.sourceUrl : null;
  const period = students?.referenceDate ? `На ${compactTrackingDate(students.referenceDate)}`
    : students?.referenceYear ? `${students.referenceYear} год` : "Дата не указана";
  return <>
    <SummaryTile label="Добавлен в отслеживание" icon={<CalendarDays />} compactValue valueSlot="institution-fact-value"
      value={added ? <time dateTime={profile!.trackingStartedAt!} title={trackingDate(profile!.trackingStartedAt!) ?? undefined}>{added}</time> : "Дата не указана"}
      note="Самая ранняя сохранённая дата добавления вуза или его аккаунтов в каталог, по московскому времени. Общая для всех площадок. Не означает, что сбор данных шёл без перерывов."
      footer="Все площадки" />
    <SummaryTile label="Студентов" icon={<GraduationCap />} valueSlot="institution-fact-value"
      value={studentCount(students)}
      note={students ? `${students.scope} Проверено ${trackingDate(students.verifiedAt)}. Численность из опубликованного источника, а не текущий счётчик.` : undefined}
      footer={source ? <a href={source} target="_blank" rel="noopener noreferrer" title={students!.sourceLabel}
        className="inline-flex max-w-full items-center gap-1 underline decoration-muted-foreground/40 underline-offset-4 hover:text-foreground focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2">
        <span>{period}{students!.approximate ? " · оценка" : ""}</span><ExternalLink aria-hidden="true" className="size-3 shrink-0" />
        <span className="sr-only"> · {students!.sourceLabel} (откроется в новой вкладке)</span>
      </a> : "Источник пока отсутствует"} />
  </>;
}
