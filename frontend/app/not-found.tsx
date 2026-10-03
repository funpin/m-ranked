import Link from "@/components/native-link";
import { buttonVariants } from "@/components/ui/button-variants";
import { Card, CardContent } from "@/components/ui/card";
import { StatusPill } from "@/components/ui";

export default function NotFound() {
  return (
    <Card className="mx-auto max-w-xl py-10">
      <CardContent className="space-y-4">
        <StatusPill tone="amber">404</StatusPill>
        <h1 className="font-heading text-2xl font-semibold tracking-tight sm:text-3xl">Данные не найдены</h1>
        <p>По этому адресу нет доступной страницы.</p>
        <Link className={buttonVariants({ variant: "outline" })} href="/" prefetch={false}>Вернуться к обзору</Link>
      </CardContent>
    </Card>
  );
}
