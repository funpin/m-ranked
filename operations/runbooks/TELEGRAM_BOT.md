# Telegram-бот — включение, выключение, откат

Бот необязателен. На проде его включают только после явного «делай» владельца. Он не входит ни в один `*.target` (`Wants=`), поэтому обычный
выпуск его не запускает и не ломается, если бота нет. Без токена юнит просто
пропускается (`ConditionPathExists=`), а не падает: падение подняло бы тревогу
«упали юниты». Миграция `0087_telegram_bot.sql` безопасна и без бота: пустые
таблицы ничего не меняют, роль `telegram_bot` создана с `NOLOGIN`.

В этом файле нет адресов, портов, токенов и Telegram ID: всё это — в заметках
оператора и на самом сервере. Бот работает только на Сервере 2.

## Что где лежит

| Что | Где |
|---|---|
| Юнит | `operations/systemd/m-ranked-target-telegram-bot.service` |
| Пример окружения | `operations/env/telegram-bot.env.example` → `/etc/m-ranked/telegram-bot.env` (необязателен) |
| Токен бота | `/etc/m-ranked/credentials/telegram-bot-token`, 0600 root, одна строка; юнит читает через `LoadCredential=` |
| Пароль базы | `/etc/m-ranked/credentials/telegram-bot-pgpass`, 0600 root, строка `.pgpass` для роли `telegram_bot` |
| Очередь тревог | `/var/lib/m-ranked/telegram-bot/inbox` |
| Состояние | таблицы `bot_*` схемы `ops_and_admin` |

Юнит запускается от `m-ranked-telegram-bot`, потолки: `MemoryMax=128M`,
`CPUQuota=20%`, `Nice=10`. Сеть: Telegram по HTTPS, локальный API сайта и
Postgres.

### Почему очередь устроена так

`alerts.py` (юнит `m-ranked-target-alerts`) работает от root, но с единственной
возможностью `CAP_DAC_READ_SEARCH`, то есть без права писать мимо прав доступа.
Поэтому каталог `inbox` принадлежит боту, группа у него `root`, права `0770`:
root пишет туда как член группы, а бот читает и удаляет файлы как владелец
каталога. Файлы событий `alerts.py` создаёт с правами `0644`, чтобы бот мог их
прочитать. Каталог создаёт `ExecStartPre=` юнита бота при каждом старте;
`alerts.py` пишет в него, только если он существует, иначе тревоги остаются в
журнале (`journalctl -u m-ranked-target-alerts`).

## Подготовка в Telegram (BotFather)

1. Создать бота, токен сохранить только в файл токена на сервере.
2. Group Privacy — включить (Enable): в группах бот видит только команды.
3. Allow Groups — выключить после того, как бот добавлен в рабочий чат:
   чужие больше не смогут добавить его в свои группы.
4. Telegram ID первого админа бот сам не знает: при первом запуске
   `TELEGRAM_BOT_ADMIN_IDS` остаётся пустым, и бот отвечает только на `/start`
   и `/id` (в журнале одно предупреждение «администраторы не заданы»). ID
   владелец получает командой `/id`, затем вписывает его в окружение.

## Включение

Всё выполняется на Сервере 2 от root, после выпуска релиза с ботом.

1. Системный пользователь:

   ```bash
   useradd --system --no-create-home --shell /usr/sbin/nologin m-ranked-telegram-bot
   ```

2. Токен:

   ```bash
   install -d -o root -g root -m 0700 /etc/m-ranked/credentials
   ( umask 077; cat > /etc/m-ranked/credentials/telegram-bot-token )  # вставить токен, Ctrl-D
   chmod 0600 /etc/m-ranked/credentials/telegram-bot-token
   ```

3. Пароль роли базы. Секрет создаётся один раз, в историю командной строки он
   не попадает:

   ```bash
   ( umask 077; openssl rand -base64 33 | tr -d '/+=\n' > /root/telegram-bot-db-secret )
   ```

   В `psql` от `mranked_bootstrap` (как для остальных ролей, см. `DEPLOY.md`):

   ```sql
   \set secret `cat /root/telegram-bot-db-secret`
   ALTER ROLE telegram_bot LOGIN PASSWORD :'secret';
   ```

   Файл `pgpass` — строка `адрес:порт:база:telegram_bot:пароль` с теми же
   значениями адреса, порта и базы, что у `maintenance-pgpass`:

   ```bash
   ( umask 077; printf '%s:%s:%s:telegram_bot:%s\n' "$DB_HOST" "$DB_PORT" "$DB_NAME" \
       "$(cat /root/telegram-bot-db-secret)" > /etc/m-ranked/credentials/telegram-bot-pgpass )
   chmod 0600 /etc/m-ranked/credentials/telegram-bot-pgpass
   shred -u /root/telegram-bot-db-secret
   ```

   (`DB_HOST`, `DB_PORT`, `DB_NAME` — переменные оболочки на время команды;
   значения берите из заметок оператора.)

4. Окружение: скопировать `operations/env/telegram-bot.env.example` в
   `/etc/m-ranked/telegram-bot.env` (0600 root) и заполнить `TELEGRAM_BOT_DSN`
   (строка libpq без пароля, роль `telegram_bot`). `TELEGRAM_BOT_ADMIN_IDS` на
   первый запуск оставить пустым (см. шаг 6).

5. Юнит:

   ```bash
   install -o root -g root -m 0644 operations/systemd/m-ranked-target-telegram-bot.service \
     /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now m-ranked-target-telegram-bot.service
   ```

6. Проверка:

   ```bash
   systemctl status m-ranked-target-telegram-bot.service --no-pager
   journalctl -u m-ranked-target-telegram-bot -n 30 --no-pager
   ```

   В журнале должна быть строка «бот запущен», а токена — нигде. В Telegram
   написать боту `/id` (ответ — ваш ID), вписать его в
   `TELEGRAM_BOT_ADMIN_IDS` в `/etc/m-ranked/telegram-bot.env` и перезапустить:
   `systemctl restart m-ranked-target-telegram-bot.service`. После этого
   `/status` отвечает сводкой по серверу. Если бот отвечает отказом в доступе —
   ID не совпал с `TELEGRAM_BOT_ADMIN_IDS`.

7. Тревоги: после первого старта каталог `inbox` существует, и `alerts.py`
   начинает класть туда события, а бот — рассылать подписанным на тревоги.

## Выключение (остальное не трогается)

```bash
systemctl disable --now m-ranked-target-telegram-bot.service
rm -rf /var/lib/m-ranked/telegram-bot/inbox
```

Без каталога `inbox` `alerts.py` возвращается к журналу, ничего не копится.
Затем закрыть вход роли (в `psql` от `mranked_bootstrap`):

```sql
ALTER ROLE telegram_bot NOLOGIN;
```

Чтобы юнит не поднялся случайно (например, при ручном запуске), уберите файл
токена: `rm /etc/m-ranked/credentials/telegram-bot-token`; без него
`ConditionPathExists=` пропускает запуск. Файл `pgpass` и `telegram-bot.env`
можно оставить или удалить. Таблицы `bot_*` остаются нетронутыми; их откат — в шапке миграции
`0087_telegram_bot.sql`.

Повторное включение — шаги 3 (новый пароль), 5 и 6 выше.

## Откат порогов alerts.py

Бот только доставляет то, что решает `alerts.py`. Если тревог слишком много или
мало, меняйте не бота, а пороги в `/etc/m-ranked/alerts.env` по таблице правил в
[TRAFFIC.md](TRAFFIC.md) (раздел «Тревоги»); примеры значений —
`operations/env/alerts.env.example`. Вернуть прежнее поведение — вернуть старые
значения в `alerts.env` (таймер подхватит их на следующем запуске, перезапуск
не нужен). Правило можно заглушить на 2 часа кнопкой «заглушить» под тревогой.

## Если что-то пошло не так

- Юнит «inactive (dead)» с пометкой о пропущенном условии — нет файла токена.
- Журнал бота показывает только имена классов исключений (без текста): это
  намеренно, текст ошибки мог бы содержать токен или адрес. Подробности — в
  журнале других служб (`m-ranked-target-api`, Postgres).
- Бот перезапускается каждые 30 секунд — смотрите, чем закончилась прошлая
  попытка: неверный пароль роли (`pgpass`), нет `TELEGRAM_BOT_DSN`, токен
  отозван. Пустой `TELEGRAM_BOT_ADMIN_IDS` — не ошибка, а режим первого запуска
  (бот отвечает только на `/start` и `/id`). Устранив причину, сбросьте счётчик
  сбоев: `systemctl reset-failed m-ranked-target-telegram-bot`.
- Тревоги не приходят, файлы копятся в `inbox` — нет получателей с включёнными
  тревогами (`/settings`) или Telegram недоступен; событий старше 6 часов бот
  отбрасывает.
