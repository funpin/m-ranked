import { Card } from "@/components/ui/card";
import type { Visitors } from "@/lib/catalog-api";
import { LazyVisitorsChart } from "./lazy-charts";
import { LiveNumber } from "./live-number";
import { OnlineNow } from "./online-now";
import { RangeSwitch } from "./range-switch";
import { Section } from "./shared";

const number = new Intl.NumberFormat("ru-RU");

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <Card className="block min-w-0 p-5">
      <p className="text-muted-foreground text-xs font-medium">{label}</p>
      <div className="mt-2">{typeof value === "number" ? <LiveNumber value={value} className="font-heading text-3xl font-semibold" /> : value}</div>
      {hint ? <p className="text-muted-foreground mt-1 text-xs">{hint}</p> : null}
    </Card>
  );
}

export function VisitorsTab({ visitors, range }: { visitors: Visitors | null; range: "week" | "month" }) {
  if (!visitors) return <Section title="Посетители"><p className="text-destructive">Не удалось получить данные о посетителях.</p></Section>;
  const closed = visitors.days.slice(0, -1);
  const average = closed.length ? Math.round(closed.reduce((sum, day) => sum + day.visitors, 0) / closed.length) : 0;
  const peak = closed.reduce((best, day) => day.visitors > best.visitors ? day : best, { day: "", visitors: 0, views: 0 });
  return <>
    <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Stat label="Сейчас на сайте" value={<OnlineNow online={visitors.online} />}
        hint={`сигнал за последние ${Math.round(visitors.onlineWindowSeconds / 60)} мин`} />
      <Stat label="Посетители сегодня" value={visitors.today.visitors} hint={`${number.format(visitors.today.views)} просмотров страниц`} />
      <Stat label={`В среднем за сутки · ${range === "week" ? "неделя" : "месяц"}`} value={average} hint="по закрытым суткам" />
      <Stat label="Лучшие сутки периода" value={peak.visitors}
        hint={peak.day ? new Date(`${peak.day}T00:00:00Z`).toLocaleDateString("ru-RU", { day: "numeric", month: "long", timeZone: "UTC" }) : "данных пока нет"} />
    </div>
    <Section title="Динамика посетителей"
      description="Уникальные посетители и просмотры по московским суткам. Без cookie: посетитель — хеш адреса и браузера с суточной солью, поэтому один человек в разные дни считается заново."
      action={<RangeSwitch label="Период" value={range} options={[["week", "Неделя"], ["month", "Месяц"]] as const}
        href={(value) => `/manage?tab=visitors&range=${value}`} />}>
      <LazyVisitorsChart days={visitors.days} />
    </Section>
  </>;
}
