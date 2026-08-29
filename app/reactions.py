from __future__ import annotations

from typing import Any, Iterable

from .models import ReactionState


def reaction_key(reaction: Any) -> str:
    emoticon = getattr(reaction, "emoticon", None)
    if emoticon is not None:
        return str(emoticon)
    document_id = getattr(reaction, "document_id", None)
    if document_id is not None:
        return f"custom:{document_id}"
    if reaction.__class__.__name__ == "ReactionPaid":
        return "paid:star"
    return f"unknown:{reaction.__class__.__name__}"


def parse_message_reactions(message: Any) -> ReactionState:
    results = getattr(getattr(message, "reactions", None), "results", None) or []
    parsed: dict[str, int] = {}
    raw: list[dict[str, Any]] = []
    for item in results:
        key = reaction_key(getattr(item, "reaction", None))
        count = int(getattr(item, "count", 0) or 0)
        parsed[key] = parsed.get(key, 0) + count
        raw.append({"key": key, "count": count})
    return ReactionState(parsed, sum(parsed.values()), raw)


def choose_album_reactions(messages: Iterable[Any]) -> tuple[ReactionState, bool]:
    states = [parse_message_reactions(message) for message in messages]
    nonempty = [state for state in states if state.raw or state.total]
    if not nonempty:
        return ReactionState({}, 0, []), False
    signatures = {(tuple(sorted(state.reactions.items())), state.total) for state in nonempty}
    chosen = max(nonempty, key=lambda state: state.total)
    raw = [
        {"element": index, "total": state.total, "reactions": state.reactions}
        for index, state in enumerate(states)
    ]
    return ReactionState(chosen.reactions, chosen.total, raw), len(signatures) > 1
