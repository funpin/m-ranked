"""Заглушка группы query: маршруты добавляются по мере порта."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["Query"])
