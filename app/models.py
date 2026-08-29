from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ReactionState:
    reactions: dict[str, int]
    total: int
    raw: list[dict[str, Any]]


@dataclass(frozen=True)
class LogicalPost:
    message_ids: tuple[int, ...]
    grouped_id: int | None
    published_at: datetime
    post_type: str
    reaction_state: ReactionState
    ambiguous_reactions: bool = False
