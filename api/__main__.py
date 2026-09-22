"""Точка входа API для обоих deployment-профилей.

Профиль A по умолчанию сохраняет один процесс: на исходном одноядерном хосте
дополнительные процессы лишь дублируют LRU. Профиль B может задать несколько
воркеров: публичный response cache у них общий в Redis, а число процессов
ограничивается измеренной CPU/DB ёмкостью Сервера 2.
"""
from __future__ import annotations

import logging

import uvicorn

from .config import Settings


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    uvicorn.run(
        "api.app:create_app", factory=True,
        host=settings.host, port=settings.port, workers=settings.workers,
        access_log=False, server_header=False, date_header=True,
    )


if __name__ == "__main__":
    main()
