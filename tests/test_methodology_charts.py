"""Данные графиков методологии совпадают с выводом настоящих детекторов."""
from __future__ import annotations

import json
import re

from anomaly_analysis.tools.methodology_charts import OUTPUT, build


def test_committed_chart_data_is_reproduced_by_the_generator() -> None:
    committed = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(build(), ensure_ascii=False))


def test_every_illustration_carries_the_detector_formula_it_shows() -> None:
    data = build()
    patterns = {"linearFeed": 1, "lateSpike": 2, "gapGrowth": 4, "catchUp": 5, "reactionsBeforeViews": 6,
                "reactionsExceedViews": 7, "synchronousRise": 8, "burstPlateau": 9, "erv": 10, "lateEngagement": 13}
    for key, pattern in patterns.items():
        sign = data[key]["sign"]
        assert sign["pattern"] == pattern and sign["formula"] and 0 < sign["strength"] <= 1, key
    # Real aggregates are anonymous: no account or publication identifiers leak into the page.
    text = json.dumps(data, ensure_ascii=False)
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text)
