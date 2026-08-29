from dataclasses import dataclass

from app.reactions import (
    choose_album_reactions,
    custom_emoji_asset,
    parse_message_reactions,
    reaction_key,
)


@dataclass
class ReactionEmoji:
    emoticon: str


@dataclass
class ReactionCustomEmoji:
    document_id: int


class ReactionPaid:
    pass


@dataclass
class Result:
    reaction: object
    count: int


@dataclass
class Reactions:
    results: list[Result]


@dataclass
class Message:
    reactions: Reactions | None


def test_reaction_parsing_and_total():
    message = Message(Reactions([Result(ReactionEmoji("👍"), 4), Result(ReactionEmoji("❤️"), 3)]))
    state = parse_message_reactions(message)
    assert state.reactions == {"👍": 4, "❤️": 3}
    assert state.total == 7


def test_custom_emoji_has_stable_identifier():
    state = parse_message_reactions(Message(Reactions([Result(ReactionCustomEmoji(123456), 9)])))
    assert state.reactions == {"custom:123456": 9}


def test_custom_emoji_asset_variants_have_static_fallbacks():
    assert custom_emoji_asset({"type": "webp", "emoji": "https://t.me/a.webp"}) == "https://t.me/a.webp"
    assert custom_emoji_asset({"type": "webm", "emoji": "https://t.me/a.webm", "thumb": "https://t.me/a.png"}) == "https://t.me/a.png"
    assert custom_emoji_asset({"type": "tgs", "emoji_static": "https://t.me/a.webp"}) == "https://t.me/a.webp"
    assert custom_emoji_asset({"type": "webm"}) is None


def test_paid_reaction_and_zero_reactions():
    assert reaction_key(ReactionPaid()) == "paid:star"
    assert parse_message_reactions(Message(None)).total == 0
    assert parse_message_reactions(Message(None)).reactions == {}


def test_album_uses_one_authoritative_state_not_sum():
    first = Message(Reactions([Result(ReactionEmoji("🔥"), 12)]))
    second = Message(None)
    state, ambiguous = choose_album_reactions([first, second])
    assert state.total == 12
    assert not ambiguous


def test_album_ambiguous_states_are_flagged_and_largest_is_retained():
    first = Message(Reactions([Result(ReactionEmoji("🔥"), 12)]))
    second = Message(Reactions([Result(ReactionEmoji("🔥"), 10)]))
    state, ambiguous = choose_album_reactions([first, second])
    assert state.total == 12
    assert ambiguous
