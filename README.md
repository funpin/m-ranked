<p align="center">
  <a href="https://m.funpin.org/" aria-label="Открыть m-ranked">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="./frontend/assets/logo-mark-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="./frontend/assets/logo-mark-light.svg">
      <img src="./frontend/assets/logo-mark-light.svg" alt="Логотип m-ranked" width="210">
    </picture>
  </a>
</p>

<h1 align="center">m-ranked</h1>

<p align="center">
  <strong>Мониторинг и сравнительная аналитика официальных соцсетей российских вузов.</strong>
</p>

<p align="center">
  <a href="https://m.funpin.org/"><img alt="Production" src="https://img.shields.io/badge/production-m.funpin.org-0082FE?style=flat-square"></a>
  <a href="https://github.com/funpin/m-ranked/actions/workflows/ci.yml"><img alt="Build and contract gates" src="https://github.com/funpin/m-ranked/actions/workflows/ci.yml/badge.svg?branch=alpha"></a>
  <img alt="Python 3.13" src="https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white">
  <img alt="FastAPI 0.141" src="https://img.shields.io/badge/FastAPI-0.141-009688?style=flat-square&amp;logo=fastapi&amp;logoColor=white">
  <img alt="Node.js 24" src="https://img.shields.io/badge/Node.js-24-339933?style=flat-square&amp;logo=nodedotjs&amp;logoColor=white">
  <img alt="Next.js 16.3" src="https://img.shields.io/badge/Next.js-16.3-111111?style=flat-square&amp;logo=nextdotjs&amp;logoColor=white">
  <img alt="PostgreSQL 18" src="https://img.shields.io/badge/PostgreSQL-18-4169E1?style=flat-square&amp;logo=postgresql&amp;logoColor=white">
</p>

---

M-Ranked собирает динамику публикаций вузов в Telegram, VK, MAX и Rutube,
хранит наблюдения в PostgreSQL и показывает рейтинги, сравнения и историю.

Production-стек один:

- FastAPI в `api/` — публичный и административный API;
- платформенные Python-сборщики в `collector_target/` и `collector_runtime/`;
- PostgreSQL 18 со схемой из `db/migrations/`;
- Next.js в `frontend/`;
- in-process LRU-кэш с инвалидацией через PostgreSQL `LISTEN/NOTIFY`.

Публичный адрес: [m.funpin.org](https://m.funpin.org).

## Быстрый старт

```bash
make venv
make stand          # http://localhost:3000
make test           # Python и frontend
```

Локальный стенд поднимает чистую PostgreSQL, FastAPI и Next.js. Демонстрационные
пароли лежат только в шаблоне `infra/local/compose.env.example`; собственный
файл можно указать через `MRANKED_COMPOSE_ENV`.

Сборщики запускаются отдельно:

```bash
.venv/bin/python -m collector_target --platform telegram
.venv/bin/python -m collector_target --platform vk
.venv/bin/python -m collector_target --platform max
.venv/bin/python -m collector_target --platform rutube
```

## Проверки

- `.venv/bin/python -m pytest tests anomaly_analysis -q`;
- `cd frontend && pnpm check`;
- чистый bootstrap: `docker compose --env-file infra/local/compose.env.example -f infra/compose.yaml up -d --wait postgres`.

Интеграционные PostgreSQL-тесты требуют DSN из `.env.test`; без них они
пропускаются. API-контракт зафиксирован в
`contracts/openapi/m-ranked-v1.yaml` и проверяется как Python-, так и
frontend-тестами.

## Документация

- [модель и страницы](docs/REFERENCE.md);
- [эксплуатация](docs/OPERATIONS.md);
- [архитектура и ADR](docs/architecture/README.md);
- [план перехода к двум профилям](docs/architecture/two-server-migration-plan.md);
- [single/two-server topology](docs/architecture/deployment-topologies.md);
- [raw transfer protocol](docs/architecture/raw-data-transfer.md);
- [развёртывание](operations/runbooks/DEPLOY.md);
- [backup и restore](operations/runbooks/BACKUP_RESTORE.md);
- [правила участия](CONTRIBUTING.md).
