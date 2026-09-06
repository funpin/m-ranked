"""Regenerate the Java import oracle by executing the unchanged legacy ranking function."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.m_rating import latest_social_rankings


def main() -> None:
    names = ["Straße", "STRASSE", "Ёлка", "елка", "İ", "i\u0307", "\ue000", "😀", "Σ", "ς", "ß", "ss"]
    items = [
        {"code": str(index + 1), "name": name, "scores": {"social": 88, "tg": "88.50", "vk": None, "ok": 0, "rt": -index}}
        for index, name in enumerate(names)
    ]
    items += [
        {"code": "\u00a019\u0085", "name": "A", "scores": {"social": "0.10", "tg": 0.0, "vk": 1, "ok": False}},
        {"code": "19", "name": "Z", "scores": {"social": "0.10", "tg": -0.0, "vk": True}},
        {"code": 0, "name": False, "scores": {"tg": 999}},
        {"code": None, "name": "Ignored code consumes rank", "scores": {"tg": 999}},
        {"code": "84", "name": None, "scores": {"social": 1.25, "tg": -3}},
        {"code": "111", "name": "No values", "scores": None},
    ]
    payloads = [
        {"months": [{"name": "Old", "items": [{"code": "old", "scores": {"tg": 9999}}]}, {"name": "Август", "items": items}, {"name": "Future", "items": [{"scores": {"tg": None}}]}]},
        {"months": [{"items": [{"code": "19", "scores": {"ok": 0}}]}]},
    ]
    fixtures = []
    for payload in payloads:
        period, rankings = latest_social_rankings(payload, 2026)
        fixtures.append({"payload": payload, "period": period, "rankings": rankings})
    path = Path(__file__).resolve().parents[2] / "backend/src/test/resources/admin/official-rating-legacy-golden.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"oracle": "app.m_rating.latest_social_rankings", "oracleSha256": hashlib.sha256(Path("app/m_rating.py").read_bytes()).hexdigest(), "cases": fixtures}, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {len(fixtures)} legacy oracle cases to {path}")


if __name__ == "__main__":
    main()
