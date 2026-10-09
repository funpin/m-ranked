import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { LoginArt } from "./login-art";
import { OtpInput } from "./otp-input";

/** Вход в админку по блоку shadcn login-04: имя, пароль и код второго фактора —
 *  три отдельных поля, а не склейка.
 *
 * Обычная форма: она отправляется и при отключённом JavaScript (поле кода —
 * настоящий input с именем otp), а учётные данные не проходят через
 * состояние страницы. Куку сессии ставит API, фасад /manage только передаёт
 * её браузеру. Ссылок «забыли пароль», входа через сервисы и регистрации
 * нет: учётные записи заводит администратор.
 */
export function AdminLogin({ failed }: { failed: boolean }) {
  return (
    <div className="mx-auto flex w-full max-w-sm flex-col gap-6 py-2 md:max-w-4xl md:py-6">
      <Card className="p-0">
        <CardContent className="grid p-0 md:grid-cols-2">
          <form className="p-6 md:p-8" method="post" action="/manage/sign-in" autoComplete="off" data-testid="admin-login">
            <FieldGroup>
              <div className="flex flex-col items-center gap-2 text-center">
                <h1 className="font-heading text-2xl font-bold tracking-tight">Вход в управление</h1>
                <p className="text-muted-foreground text-sm text-balance">Закрытая панель m-ranked: каналы, посетители и состояние системы</p>
              </div>
              <FieldError className="border-destructive/30 bg-destructive/10 rounded-md border px-3 py-2 text-sm">
                {failed ? "Неверные учётные данные или код. Попробуйте ещё раз со свежим кодом." : null}
              </FieldError>
              <Field>
                <FieldLabel htmlFor="admin-username" className="text-sm">Имя пользователя</FieldLabel>
                <Input id="admin-username" name="username" autoComplete="username" maxLength={200} required className="h-9 text-sm md:text-sm" />
              </Field>
              <Field>
                <FieldLabel htmlFor="admin-password" className="text-sm">Пароль</FieldLabel>
                <Input id="admin-password" name="password" type="password" autoComplete="current-password" maxLength={1024} required className="h-9 text-sm md:text-sm" />
              </Field>
              <Field>
                <FieldLabel htmlFor="admin-otp" className="text-sm">Код подтверждения</FieldLabel>
                <OtpInput id="admin-otp" name="otp" />
                <FieldDescription>Шесть цифр из приложения-аутентификатора. Код действует один раз.</FieldDescription>
              </Field>
              <Field>
                <Button type="submit" className="h-9 text-sm">Войти</Button>
              </Field>
            </FieldGroup>
          </form>
          <div className="bg-muted relative hidden min-h-[30rem] md:block">
            <LoginArt />
          </div>
        </CardContent>
      </Card>
      <FieldDescription className="px-6 text-center">
        Учётные записи заводит администратор. Число попыток входа ограничено.
      </FieldDescription>
    </div>
  );
}

/** Выход: сессия гасится на сервере, кука истекает. */
export function AdminSignOut({ csrf }: { csrf: string }) {
  return (
    <form method="post" action="/manage/sign-out">
      <input type="hidden" name="csrf_token" value={csrf} />
      <Button type="submit">Выйти</Button>
    </form>
  );
}
