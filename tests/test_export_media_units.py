from __future__ import annotations

from api.emoji_proxy import allowed_url, public_address
from api.exporting import modern_cell, write_csv
from api.routes.exports import LEGACY_HEADERS, _legacy_cell, _legacy_platform


def test_legacy_csv_writer_matches_python_dialect(tmp_path) -> None:
    target = tmp_path / "legacy.csv"
    write_csv(target, LEGACY_HEADERS[("posts", "telegram")], [
        ("=formula", "a,\"b\"\r\nЮ", None, "0", "-2", "", "", "", ""),
    ], max_rows=10, max_bytes=10000, max_seconds=1, transform=_legacy_cell)
    assert target.read_bytes() == (
        "канал,id_публикации,опубликовано,полная_история,последнее_число_реакций,"
        "последнее_число_просмотров,последнее_число_комментариев,максимальный_скачок,"
        "возраст_скачка_часов\r\n"
        '=formula,"a,""b""\r\nЮ",,0,-2,,,,\r\n'
    ).encode()


def test_modern_csv_neutralizes_formula_after_control_prefix() -> None:
    assert modern_cell("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert modern_cell("\x00  @command") == "'\x00  @command"
    assert modern_cell("normal") == "normal"


def test_legacy_platform_uses_last_value_and_python_whitespace() -> None:
    assert _legacy_platform(["vk", " TG "]) == "telegram"
    assert _legacy_platform(["\u00a0ОБЩИЙ\u0085"]) == "all"
    assert _legacy_platform(["unknown"]) == "telegram"


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
