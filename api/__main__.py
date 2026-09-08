"""Точка входа: один процесс uvicorn.

Сервер держит одно ядро, поэтому воркер один: параллелизм даёт цикл событий,
а не процессы. Второй воркер получил бы свой кэш в памяти — оба слушают
NOTIFY, так что расхождения не будет, но и выигрыша на одном ядре тоже.
"""
from __future__ import annotations

import logging

import uvicorn

from .app import create_app
from .config import Settings


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port,
                access_log=False, server_header=False, date_header=True)


if __name__ == "__main__":
    main()
