# Холодный архив, серверы и хранение (ADR-016)

Адреса, порты и ключи сюда не записываются.

## Выкатка на основной сервер (Сервер 2)

1. Миграция `0057_storage_nodes_and_policies.sql`. Политики сбора и анализа
   в ней пустые, поэтому до решения администратора поведение не меняется.
2. Группа хранилища, каталог и `pyarrow` для конвейера (вне venv API):

   ```bash
   groupadd -f m-ranked-storage
   usermod -aG m-ranked-storage m-ranked-transfer-ingest
   usermod -aG m-ranked-storage m-ranked-maintenance
   install -d -m 2775 -g m-ranked-storage /var/lib/m-ranked/store
   pip install --target /opt/m-ranked/ops-libs pyarrow==25.0.1
   ```

3. Юниты на Сервере 2 правятся drop-in'ами, файлы из репозитория поверх не
   ставятся. Приёмнику переноса нужен drop-in:

   ```ini
   [Service]
   SupplementaryGroups=m-ranked-storage
   ReadWritePaths=-/var/lib/m-ranked/store
   ```

   В `transfer-ingest.env` добавить `TRANSFER_INGEST_NODE_HUB=on` и
   `MRANKED_STORE_DIR=/var/lib/m-ranked/store`.
4. Новые юниты:
   - `m-ranked-target-storage-main.{service,timer}` — агент основного сервера,
     раз в минуту;
   - `m-ranked-target-cold-archive.{service,timer}` — конвейер, раз в сутки;
   - `m-ranked-target-archive-analysis.service` — его запускает агент, когда
     в панели поставлено задание.

   Включить таймеры:

   ```bash
   systemctl enable --now m-ranked-target-storage-main.timer m-ranked-target-cold-archive.timer
   ```

## Сервер-сборщик

1. Отправитель переноса уже настроен: сертификат с именем сервера и
   `COLLECTOR_TRANSFER_HTTPS_ENDPOINT`.
2. Поставить `m-ranked-target-node-agent.{service,timer}`. Если релиз лежит не
   в `/opt/m-ranked/current`, как на Сервере 1, нужен drop-in с
   `WorkingDirectory=` каталога релиза.
3. В окружение сборщиков добавить
   `COLLECTOR_RUNTIME_POLICY_FILE=/var/lib/m-ranked/node-agent/runtime.json`.
4. Добавить сервер в панели, вкладка «Серверы»: имя как в сертификате,
   площадки, «подключить сразу». Приёмник начнёт принимать данные с него
   в течение 30 секунд.

## Как проверить

- На вкладке «Серверы» у каждого сервера отметка «на связи», видны диск и
  память.
- Ближайший дамп появляется в «Резервных копиях по серверам» с копией на
  втором сервере (если хватает места сверх запаса).
- Месяц переходит в архив кнопкой «Архивировать созревшие» или ночным
  таймером. Ход виден в «Холодном архиве» и в журнале
  `journalctl -u m-ranked-target-cold-archive`.

## Если что-то пошло не так

- **Копия не доехала за два часа.** Месяц открывается, поколение получает
  статус «не удалось», файлы выводятся из оборота. Следующий запуск выгрузит
  месяц заново. Данные в базе не тронуты.
- **Пропал файл просмотра на основном сервере.** Агент заказывает копию
  заново: файл просмотра хранится и на серверах `archiveNodes`, если они
  отмечены. Пока копии нет, API отвечает 503 на архивные посты.
- **Восстановление месяца в базу.** Готовой команды пока нет. Полный Parquet
  месяца (любая сверенная копия) содержит все колонки
  `publication_metric_snapshot` и разбивку реакций. Его читают `pyarrow`, строки
  вставляют в пустую партицию месяца, а совпадение проверяют
  `publication_partition_digest` против `canonical_sha256` из манифеста.

## Локальная проверка

Интеграционный тест полного цикла на одноразовой базе (секунды):

```bash
docker run -d --name mranked-archive-test -p 127.0.0.1:55499:5432 -e POSTGRES_PASSWORD=pg -e POSTGRES_DB=mranked …  # см. infra/postgres/init
MRANKED_TEST_ARCHIVE_ADMIN_DSN=… MRANKED_TEST_ARCHIVE_MAINTENANCE_DSN=… MRANKED_TEST_ARCHIVE_WORKER_DSN=… \
  .venv/bin/python -m pytest -q tests/test_cold_archive_pipeline_postgres.py
```
