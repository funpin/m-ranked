from __future__ import annotations

from api.emoji_proxy import allowed_url, public_address


def test_emoji_url_and_address_policy() -> None:
    assert allowed_url("https://t.me/i/emoji/42.json")
    assert allowed_url("https://cdn1.telegram.org/emoji/42.webp")
    assert allowed_url("https://media.telesco.pe/static.webp")
    for forbidden in (
        "http://t.me/a", "https://user@t.me/a", "https://t.me:444/a",
        "https://t.me/a#fragment", "https://telegram.org.evil.example/a",
    ):
        assert allowed_url(forbidden) is None
    for forbidden in ("127.0.0.1", "10.0.0.1", "169.254.1.1", "::1", "2001:db8::1"):
        assert not public_address(forbidden)
    assert public_address("8.8.8.8")
