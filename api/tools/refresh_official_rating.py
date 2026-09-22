"""Ежедневная проверка официального М-Рейтинга.

Источник обновляется раз в месяц, поэтому почти каждый прогон не находит
ничего нового и заканчивается ничем. Смысл ежедневной проверки в том, что
новый месяц попадает в базу в день публикации, а не когда кто-нибудь вспомнит
нажать кнопку в панели управления: до этой правки в базе лежал ровно один
период, и сравнивать место в рейтинге было не с чем.

Запускается расписанием, а не из панели: у обновления нет ни пользователя, ни
формы, и держать ради него открытый административный путь незачем.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import date
from types import SimpleNamespace

from ..config import Settings
from ..db import Database
from ..official_rating import refresh

logger = logging.getLogger("official-rating")

ACTOR = "schedule"
# Пространство имён корреляций этого задания: идентификатор выводится из даты,
# поэтому повторный запуск в те же сутки узнаётся импортом как уже виденный.
NAMESPACE = uuid.UUID("5f4d3c2b-1a09-4e8d-b7c6-0a1b2c3d4e5f")


def _carrier(database: Database) -> SimpleNamespace:
    """Обновление читает состояние приложения, а нужна ему только база."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=database)))


async def _run() -> int:
    settings = Settings()
    database = Database(settings)
    await database.open()
    try:
        # Идентификатор выводится из даты: повторный запуск в те же сутки
        # импорт узнаёт как уже виденный и ничего не делает дважды.
        correlation = uuid.uuid5(NAMESPACE, date.today().isoformat())
        await refresh(_carrier(database), ACTOR, correlation)
        logger.info("официальный рейтинг проверен")
        return 0
    except Exception as error:
        logger.error("проверка официального рейтинга не удалась: %s", type(error).__name__)
        return 1
    finally:
        await database.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
