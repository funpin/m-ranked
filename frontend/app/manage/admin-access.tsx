import { NativeButton, NativeInput as Input } from "@/components/native-field";

/** Вход в админку: имя, пароль и код — три отдельных поля, а не склейка.
 *
 * Обычная форма без скриптов: она работает при отключённом JavaScript, а сами
 * учётные данные не проходят через состояние страницы. Куку сессии ставит API,
 * фасад /manage только передаёт её браузеру.
 */
export function AdminLogin({ failed }: { failed: boolean }) {
  return (
    <section className="mx-auto grid max-w-md gap-4 rounded-xl border bg-card p-5 text-card-foreground shadow-sm">
      <div>
        <h1 className="font-heading text-xl font-semibold">Вход в управление</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">Код из приложения-аутентификатора вводится отдельным полем и тратится один раз.</p>
      </div>
      {failed ? <p className="text-sm text-destructive" role="alert">Неверные учётные данные или код. Попробуйте ещё раз со свежим кодом.</p> : null}
      <form className="grid gap-3" method="post" action="/manage/sign-in" autoComplete="off" data-testid="admin-login">
        <label className="grid gap-1.5 text-sm"><span>Имя пользователя</span><Input name="username" autoComplete="username" maxLength={200} required /></label>
        <label className="grid gap-1.5 text-sm"><span>Пароль</span><Input name="password" type="password" autoComplete="current-password" maxLength={1024} required /></label>
        <label className="grid gap-1.5 text-sm"><span>Код подтверждения</span><Input name="otp" inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" maxLength={6} required /></label>
        <NativeButton type="submit">Войти</NativeButton>
      </form>
    </section>
  );
}

/** Выход: сессия гасится на сервере, кука истекает. */
export function AdminSignOut({ csrf }: { csrf: string }) {
  return (
    <form method="post" action="/manage/sign-out">
      <input type="hidden" name="csrf_token" value={csrf} />
      <NativeButton type="submit">Выйти</NativeButton>
    </form>
  );
}
