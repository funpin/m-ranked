# m-ranked

В ветке `alpha` единственный интерфейс — **Next.js (`frontend/`) + Spring
(`backend/`)**. Старый Python-интерфейс, его шаблоны и команды `web`/`run`
удалены. [Локальный Docker-стенд](infra/local/README.md) открывается на
http://localhost:3000. Python-код сборщиков и миграции данных сохранён.

Монитор динамики публикаций вузов в Telegram, VK, MAX и Rutube.
Новая версия хранит UTC-замеры всех площадок в PostgreSQL и читает рассчитанные
показатели из общей схемы `analytics`. Сборщики читают данные площадок;
управление вузами и аккаунтами доступно в защищённой панели `/manage`.

Единственный рабочий адрес: [m.funpin.org](https://m.funpin.org).
Других рабочих зеркал и доменов у сервиса сейчас нет. Переход на домен `.org`
связан с зарубежным расположением хостинга.

Сейчас проект независимо собирает и показывает историю Telegram, VK, MAX и
Rutube, строит рейтинги и сравнение для поддерживаемых площадок, выгружает
сырые снимки в CSV и показывает состояние каждого сборщика через `/health`.
Сборщики запускаются параллельно и не задерживают расписание друг друга.
Точные комментарии Telegram доступны через авторизованную по номеру сессию
официального Telegram Web K без приложения на `my.telegram.org` и без внешних
агрегаторов.
MAX подключён через отдельную пользовательскую сессию: сборщик получает точные
просмотры, общее число и состав реакций, а для подключённых обсуждений — явно
показанный MAX счётчик комментариев. Для публикаций строятся канонические
публичные ссылки `max.ru/{канал}/{slug}`.

## Быстрый старт

```bash
make venv          # окружение Python
make stand         # локальный стенд в Docker, http://localhost:3000
make test          # быстрые гейты: Python, Spring, фронтенд
make gates         # плюс jar и полный интеграционный runner
```

`make help` перечисляет остальные цели. Стенд на копии production-базы
поднимается через `make stand-prodcopy COPY=<каталог> ENV=<файл>`, подробности
в [infra/local/README.md](infra/local/README.md).

## Документация

| Документ | О чём |
|---|---|
| [docs/REFERENCE.md](docs/REFERENCE.md) | Модель данных, формулы интерфейса, страницы |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Развёртывание, сборщики, конфигурация, частота сбора |
| [docs/architecture/](docs/architecture/) | Архитектура, ADR, модель угроз |
| [docs/database/](docs/database/) | Решения по схеме и аудиты хранилища |
| [docs/features/anomaly-analysis.md](docs/features/anomaly-analysis.md) | Анализ аномальной динамики |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) | API-интеграции площадок |
| [docs/MULTIPLATFORM.md](docs/MULTIPLATFORM.md) | Мультиплатформенная модель |
| [docs/ROADMAP.md](docs/ROADMAP.md), [docs/TODO.md](docs/TODO.md) | Планы |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Раскладка репозитория, инструменты, порядок проверок |
| [operations/runbooks/](operations/runbooks/) | Ранбуки эксплуатации |

## Проверки текущего стека

- `rtk .venv/bin/python -m pytest -q` — Python-сборщики, совместимость данных,
  миграция и эксплуатационные проверки. Без тестовых DSN интеграционные тесты
  PostgreSQL пропускаются; это не полный прогон.
- В `frontend/`: `rtk pnpm check` — Node 24, типы, API-контракт, unit-тесты,
  браузерные сценарии desktop/mobile и production-сборка.
- `rtk docker compose -f infra/compose.yaml up -d --wait postgres` — создаёт
  пустую PostgreSQL сразу по `final-schema.sql`; затем проверяется
  `ops_and_admin.schema_contract` и отсутствие `flyway`/`migration` schemas.

SQLite-тесты сохранены для ещё используемого Python-кода и чтения архивных
артефактов, но не являются способом установки PostgreSQL. Обязательный CI
проверяет прямой bootstrap финальной схемы, Java/Python suites и текущие
браузерные сценарии.

Workflow [Required migration gates](.github/workflows/migration.yml) запускается
при pull request и push в `alpha`/`main`. Имена проверок сохранены:

| Проверка GitHub | Состав |
| --- | --- |
| `canonical-integrity` | Чистая установка финальной схемы, Spring, Python, PostgreSQL/Redis и восстановление |
| `browser-parity` | Типы, OpenAPI, unit/E2E, 20 маршрутов реального сравнения статусов и UUID, сборка и размер bundle |

[Карта тестов и результаты локальной проверки](tests/README.md)
объясняют сохранённые SQLite-тесты и обязательные интеграционные этапы.

## Локальная разработка

Для всего стека нужны Docker Compose, Java 21, Node 24 и Python 3.13.
Maven Wrapper находится в `backend/mvnw`, версия pnpm закреплена в
`frontend/package.json`. Инструкции по компонентам:
[frontend](frontend/README.md), [сборка backend](migration/integration/README.md),
[локальный Docker-стенд и его сохранённые данные](infra/local/README.md).
Новый пустой стенд для проверки миграций создаёт интеграционный runner.

```bash
rtk python3.13 -m venv .venv
rtk .venv/bin/python -m pip install -r requirements.txt -r operations/requirements.txt
rtk .venv/bin/python -m pytest -q
```

Обычные тесты используют фикстуры; полный интеграционный прогон создаёт
временные PostgreSQL/Redis. Реальные сессии и токены площадок для них не нужны.
