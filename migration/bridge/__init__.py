"""Idempotent M-Ranked legacy data bridge."""

from .model import (
    BRIDGE_NAMESPACE,
    BridgeOptions,
    SourceInventory,
    stable_bigint,
    stable_uuid,
)
from .source import LegacySource, create_online_backup

__all__ = [
    "BRIDGE_NAMESPACE",
    "BridgeOptions",
    "LegacySource",
    "SourceInventory",
    "create_online_backup",
    "stable_bigint",
    "stable_uuid",
]
