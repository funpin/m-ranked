# Панель управления: посетители, состояние системы, авторы

Вкладки «Посетители» и «Система» панели `/manage` и авторы в шапке сайта
работают на трёх механизмах. Все они читают уже имеющиеся на сервере данные и
ничего не считают в момент запроса страницы.

| Что | Где живёт | Нагрузка |
| --- | --- | --- |
| Снимок сервера | таймер `m-ranked-target-ops-sample` раз в минуту → `ops_and_admin.host_sample` (миграция 0052) | около секунды; раз в 6 часов `du` по каталогам проекта (~15 с процессора на Сервере 2) на `IOSchedulingClass=idle`, лимит 128 МБ и 25 % ядра |
| Посетители | маячок `POST /api/v1/visit` → буфер в API → пачка раз в 30 с в `ops_and_admin.site_visitor` (миграция 0053) | одна вставка на 30 с на процесс API; nginx режет маячок до 1 запроса в секунду с адреса |
| Авторы | таймер `m-ranked-target-contributors` раз в трое суток → `/var/lib/m-ranked/contributors` | два-три запроса к GitHub |

Хранение: снимки — 30 суток (≈ 43 000 строк по ~1 КБ), посетители — строка на
посетителя текущих суток, итог — строка на сутки.

## Что собирает снимок

- `/proc/stat`, `/proc/meminfo`, `/proc/loadavg`, свободное место раздела `/`;
- состояние юнитов `m-ranked-*`, `nginx`, `docker` и счётчик автоматических
  перезапусков долгоживущих служб;
- прирост журнала `/var/log/nginx/m-ranked-access.log` с прошлого снимка:
  запросы, люди и роботы, коды ответа, попадания в страничный кэш, p50/p95
  времени ответа страниц людям. Позиция в журнале хранится в
  `/var/lib/m-ranked/ops-sample/state.json`; поворот журнала узнаётся по inode;
- метрики служб из `/var/lib/node_exporter/textfile_collector`: приём с
  Сервера 1, очередь и прогоны анализа, резервная копия;
- итоги опроса аккаунтов, завершённых с прошлого снимка
  (`ingest.collection_run` → `collection_account_result` по индексам);
- раз в 6 часов — размеры `/opt/m-ranked`, `/var/lib/m-ranked`, `/var/cache/nginx`
  через `du` (недоступный подкаталог пропускается, а не обрывает счёт). Дороже
  всего страничный кэш nginx: сотни тысяч мелких файлов.

Служба работает под `m-ranked-maintenance` с ролью базы `maintenance` и
единственной возможностью `CAP_DAC_READ_SEARCH` — читать чужие каталоги и
журнал nginx. Пути задаются в `/etc/m-ranked/maintenance.env`
(`OPS_SAMPLE_*`, см. `operations/env/maintenance.env.example`).

Проверки вкладки «Система» используют те же пороги, что тревоги
(`operations/scripts/alerts.py`); проверка «Снимок сервера» падает, если
снимков нет дольше 5 минут.

## Посетители без cookie

Посетитель — BLAKE2b(суточная соль ‖ адрес ‖ браузер). Адрес не записывается,
соль одна на сутки для всех процессов API (`ops_and_admin.visit_salt`) и
удаляется вместе с подведением итога суток (после 00:05 МСК). Поэтому:

- уникальные посетители считаются за московские сутки; неделя и месяц — ряд
  суточных значений, а не уникальные за период;
- «сейчас на сайте» — разные посетители с сигналом за последние 5 минут;
  страница шлёт сигнал раз в минуту, пока вкладка видна, в базу он попадает
  в течение 30 секунд;
- роботы по User-Agent, автоматизированные браузеры (`navigator.webdriver`) и
  сама панель не считаются.

Маячок идёт в API напрямую (`location = /api/v1/visit` в `site.conf`), мимо
шлюза рендера и без записи в журнал доступа. Без административного соединения
с базой (`API_WRITE_ADMIN_DB_*`) счётчик выключен, маячок просто отвечает 204.

## Выкатка

1. Миграции `0052_ops_host_sample.sql` и `0053_site_visits.sql` — до кода, как
   обычно (раздел 2 `DEPLOY.md`). Обе только создают таблицы.
2. Дописать в `/etc/m-ranked/maintenance.env` переменные `OPS_SAMPLE_*` из
   примера (значения по умолчанию совпадают с Сервером 2).
3. nginx: зона `m_ranked_visit` в `traffic.conf` и `location = /api/v1/visit`
   в `site.conf`; `nginx -t`, затем `systemctl reload nginx`.
4. Юниты `m-ranked-target-ops-sample.{service,timer}` и
   `m-ranked-target-contributors.{service,timer}`, обновлённый
   `m-ranked-target-web.service` (`MRANKED_CONTRIBUTORS_DIR`):
   `systemctl daemon-reload`, `systemctl enable --now` обоих таймеров.
   Первый запуск авторов — вручную: `systemctl start m-ranked-target-contributors`.
5. Переключение релиза и перезапуск API и web (раздел 7 `DEPLOY.md`).

## Проверка

```bash
systemctl start m-ranked-target-ops-sample && journalctl -u m-ranked-target-ops-sample -n 3 --no-pager
systemctl list-timers 'm-ranked-target-ops-sample*' 'm-ranked-target-contributors*' --no-pager
ls /var/lib/m-ranked/contributors/avatars
```

На вкладке «Система» через пару минут появляются графики, сразу после первого снимка — размер
проекта в «Использовании хранилища». Вкладка «Посетители» показывает
«Сейчас на сайте» не меньше одного, если открыть сайт в соседней вкладке.

## Откат

Таймеры можно остановить без последствий для сайта:
`systemctl disable --now m-ranked-target-ops-sample.timer m-ranked-target-contributors.timer`.
Без снимков вкладка «Система» показывает «Снимков нет», шапка — авторов из
сборки. Таблицы удаляются строками отката в заголовках миграций 0052 и 0053.

## Резервная копия из панели

Кнопка «Обновить резервную копию» на вкладке «Система» (роль ADMIN) кладёт
файл-запрос `/var/lib/m-ranked/backup-request/refresh` (каталог API создаёт
сам, `StateDirectory`). `m-ranked-target-dump-backup-request.path` запускает
обычный `m-ranked-target-dump-backup.service`; скрипт удаляет файл и перед
снимком оставляет только копию, прошедшую проверку восстановлением
(`rotate-dumps.py --refresh`). После снимка на диске ровно две копии. Ход
снимка (запрошен, идёт, размер недоснятого файла, результат) панель видит по
снимку сервера раз в минуту.

## Диагностика: mranked-doctor

`/usr/local/sbin/mranked-doctor` — ссылка на
`/opt/m-ranked/current/operations/scripts/mranked-doctor.py`. Только читает:
упавшие службы с выдержкой журнала, таймеры, health API и веба, конвейер,
диск и резервные копии, 5xx и медленные ответы nginx за час, состояние базы,
ошибки журналов служб за час. Код выхода 1 и список «problems» — если есть
что чинить.

```bash
ssh <сервер 2> mranked-doctor
ssh <сервер 2> mranked-doctor --json --section units,storage
```

С машины оператора — `operations/scripts/remote-doctor.sh` (параметры ssh в
`MRANKED_S2_SSH`).

Кандидаты выкатки (`systemd-run` на порту 3007) запускать с `--collect`:
иначе после остановки они остаются в состоянии failed и шумят в проверках.
