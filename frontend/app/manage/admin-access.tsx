import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** Вход в админку: имя, пароль и код — три отдельных поля, а не склейка.
 *
 * Обычная форма без скриптов: она работает при отключённом JavaScript, а сами
 * учётные данные не проходят через состояние страницы. Куку сессии ставит API,
 * фасад /manage только передаёт её браузеру.
 */
export function AdminLogin({ failed }: { failed: boolean }) {
  return (
    <Card className="mx-auto grid max-w-md gap-4 p-5 text-sm">
      <div>
        <h1 className="font-heading text-xl font-semibold">Вход в управление</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">Код из приложения-аутентификатора вводится отдельным полем и тратится один раз.</p>
      </div>
      {failed ? <p className="text-sm text-destructive" role="alert">Неверные учётные данные или код. Попробуйте ещё раз со свежим кодом.</p> : null}
      <form className="grid gap-3" method="post" action="/manage/sign-in" autoComplete="off" data-testid="admin-login">
        <Label className="grid gap-1.5 text-sm leading-normal font-normal"><span>Имя пользователя</span><Input name="username" autoComplete="username" maxLength={200} required /></Label>
        <Label className="grid gap-1.5 text-sm leading-normal font-normal"><span>Пароль</span><Input name="password" type="password" autoComplete="current-password" maxLength={1024} required /></Label>
        <Label className="grid gap-1.5 text-sm leading-normal font-normal"><span>Код подтверждения</span><Input name="otp" inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" maxLength={6} required /></Label>
        <Button type="submit">Войти</Button>
      </form>
    </Card>
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
