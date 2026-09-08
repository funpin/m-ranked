"""Общая оснастка тестов.

Тесты API требуют живой базы. Если подключение не задано, они пропускаются:
обычный прогон pytest не должен требовать поднятого Postgres.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env.test", override=False)

API_DATABASE_VARS = ("API_READ_DB_HOST", "API_READ_DB_USER", "API_READ_DB_PASSWORD", "API_READ_DB_NAME")


def api_database_configured() -> bool:
    return all(os.environ.get(name) for name in API_DATABASE_VARS)


requires_api_database = pytest.mark.skipif(
    not api_database_configured(),
    reason="не задано подключение к базе (API_READ_DB_*)",
)
