import json
import os
from pathlib import Path

import pytest

from api.tools import refresh_contributors as tool

LISTING = [
    {"login": "akk0sfx", "type": "User", "contributions": 140,
     "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4"},
    {"login": "dependabot[bot]", "type": "Bot", "contributions": 9,
     "avatar_url": "https://avatars.githubusercontent.com/in/2?v=4"},
    {"login": "funpin", "type": "User", "contributions": 80,
     "avatar_url": "https://avatars.githubusercontent.com/u/3?v=4"},
    {"login": "evil", "type": "User", "contributions": 1, "avatar_url": "https://example.com/x.png"},
]


def github(images: dict[str, bytes]):
    def get(url: str) -> tuple[bytes, str]:
        if url.startswith("https://api.github.com/"):
            return json.dumps(LISTING).encode(), "application/json"
        assert url.endswith("&s=64")
        return images[url.split("/u/")[1].split("?")[0]], "image/png"
    return get


def test_refresh_writes_people_and_hashed_avatars(tmp_path: Path) -> None:
    count = tool.refresh(tmp_path, github({"1": b"one", "3": b"three"}), now=1000.0)
    assert count == 2
    people = json.loads((tmp_path / "contributors.json").read_text())
    assert [person["login"] for person in people] == ["akk0sfx", "funpin"]
    assert people[0]["contributions"] == 140 and people[0]["url"] == "https://github.com/akk0sfx"
    name = people[0]["avatar"].removeprefix("/contributors/live/")
    assert (tmp_path / "avatars" / name).read_bytes() == b"one"
    assert name.startswith("akk0sfx-") and name.endswith(".png")


def test_changed_avatar_gets_a_new_name_and_old_one_lives_a_week(tmp_path: Path) -> None:
    tool.refresh(tmp_path, github({"1": b"one", "3": b"three"}), now=1000.0)
    old = sorted(path.name for path in (tmp_path / "avatars").iterdir())
    tool.refresh(tmp_path, github({"1": b"new", "3": b"three"}), now=2000.0)
    current = sorted(path.name for path in (tmp_path / "avatars").iterdir())
    assert set(old) < set(current)
    for path in (tmp_path / "avatars").iterdir():
        os.utime(path, (0, 0))
    tool.refresh(tmp_path, github({"1": b"new", "3": b"three"}), now=tool.STALE_SECONDS + 10)
    assert len(list((tmp_path / "avatars").iterdir())) == 2


def test_failure_keeps_previous_listing(tmp_path: Path) -> None:
    tool.refresh(tmp_path, github({"1": b"one", "3": b"three"}), now=1000.0)
    before = (tmp_path / "contributors.json").read_text()

    def broken(url: str) -> tuple[bytes, str]:
        if url.startswith("https://api.github.com/"):
            return json.dumps(LISTING).encode(), "application/json"
        return b"<html>", "text/html"

    with pytest.raises(ValueError):
        tool.refresh(tmp_path, broken, now=2000.0)
    assert (tmp_path / "contributors.json").read_text() == before
