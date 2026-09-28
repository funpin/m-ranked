"""Ответ анализа v2 без базы: схема OpenAPI, пост без анализа, тексты ADR-006."""
from __future__ import annotations

from datetime import timedelta
import pathlib

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
import yaml

from api.routes import analysis
from anomaly_analysis.v2 import levels
from anomaly_analysis.v2.store import quality_payload, sign_payload
from anomaly_reference.mature_norms import norms_for, synthetic_cases

CONTRACT = yaml.safe_load((pathlib.Path(__file__).resolve().parents[1]
                           / "contracts/openapi/m-ranked-v1.yaml").read_text(encoding="utf-8"))
FORBIDDEN = ("накрут", "мошен", "фальсиф", "нечестн", "доказанн")


def _validate(body: dict, name: str = "PublicationAnomalyAnalysis") -> None:
    registry = Registry().with_resource("urn:contract", Resource.from_contents(CONTRACT, default_specification=DRAFT202012))
    schema = {"$ref": f"urn:contract#/components/schemas/{name}"}
    errors = list(Draft202012Validator(schema, registry=registry).iter_errors(body))
    assert not errors, [f"{list(error.path)}: {error.message}" for error in errors]


def test_publication_without_analysis_is_a_pending_200_body():
    body = analysis.analysis_body("99269506-1466-5e18-a215-a3db2688d786", 12, None)
    _validate(body)
    assert body["status"] == "pending" and body["level"] is None
    assert body["levelLabel"] == "ещё не проанализирован" and body["signals"] == []


def test_stored_verdict_is_served_as_is_and_matches_the_contract():
    case = synthetic_cases()["owner_vk_497246_linear_with_leading_likes"]
    verdict = levels.assess(case.subject, case.siblings, norms=norms_for(case), subscribers=case.subscribers)
    moment = case.subject.observed_at[-1]
    row = {"level": int(verdict.level), "signals": [sign_payload(sign) for sign in verdict.signs],
           "quality": quality_payload(verdict.quality), "analyzed_at": moment, "lag_seconds": 40,
           "norm_version_id": 3, "detector_versions": dict(verdict.detector_versions),
           "review_status": "unreviewed"}
    body = analysis.analysis_body(str(case.subject.publication_id), 12, row)
    _validate(body)
    assert body["level"] == 3 and body["levelLabel"] == "признаки искусственной активности"
    assert {item["pattern"] for item in body["signals"]} >= {1, 6}
    assert body["analyzedAt"] == moment.isoformat() and body["normVersion"] == 3
    # Признак без анализа тоже укладывается в схему: пост анализировался, но ничего нет.
    empty = analysis.analysis_body("99269506-1466-5e18-a215-a3db2688d786", 12,
                                   {**row, "level": 0, "signals": [], "analyzed_at": moment - timedelta(hours=1)})
    _validate(empty)


def test_context_cap_changes_public_level_but_preserves_original_signals():
    moment = synthetic_cases()["owner_vk_497246_linear_with_leading_likes"].subject.observed_at[-1]
    signal = {"pattern": 2, "symbol": "⚡", "title": "Поздний скачок", "family": "shape",
              "metric": "views", "strength": .87, "startAt": moment.isoformat(),
              "endAt": (moment + timedelta(hours=1)).isoformat(), "scaleSeconds": 900,
              "formula": "факт выше ожидания", "render": {"kind": "expected", "startAge": 0, "endAge": 3600},
              "alternatives": [], "normConfidence": 1.0}
    row = {"level": 1, "original_level": 2, "recheck_reason": "new_post_and_shared_old_growth",
           "recheck_method_version": "late-view-context-cap-v1",
           "recheck_evidence": {"windows": [{"measuredOldPosts": 2}]},
           "signals": [signal], "quality": {"coverage": 1, "summary": "замеры полные", "codes": [],
                                      "unanalyzable": []}, "analyzed_at": moment, "lag_seconds": 0,
           "norm_version_id": 1, "detector_versions": {}, "review_status": "unreviewed"}
    body = analysis.analysis_body("99269506-1466-5e18-a215-a3db2688d786", 12, row)
    _validate(body)
    assert body["level"] == 1 and body["originalLevel"] == 2
    assert body["levelLabel"] == "слабый сигнал" and body["signals"] == [signal]


def test_api_level_words_match_the_analysis_module_and_the_glossary():
    assert analysis.LEVEL_LABELS == levels.LEVEL_LABELS
    assert analysis.LEVEL_SYMBOLS == levels.LEVEL_SYMBOLS
    for text in (*analysis.LEVEL_LABELS.values(), analysis.DISCLAIMER, analysis.NOT_ANALYZED):
        assert not any(word in text.lower() for word in FORBIDDEN), text


def test_analysis_cache_is_not_invalidated_by_ingestion():
    assert analysis.ANALYSIS_TAGS == frozenset({"analysis"})


def test_account_levels_carry_only_the_level_words():
    body = analysis.levels_body("99269506-1466-5e18-a215-a3db2688d786", 12, [
        {"publication_id": "0f0cb3a4-7b1e-5c43-9d44-1d5d0b1f5a01", "level": 3},
        {"publication_id": "0f0cb3a4-7b1e-5c43-9d44-1d5d0b1f5a02", "level": 0},
    ])
    _validate(body, "AccountAnomalyLevels")
    assert [item["levelLabel"] for item in body["items"]] == [
        "признаки искусственной активности", "нет признаков"]


def test_new_reference_signals_use_the_public_contract():
    from datetime import datetime, timezone
    from uuid import UUID
    from anomaly_analysis.v2.domain import PostSeries, Metric
    from anomaly_analysis.v2.mature_reference import bundled_reference
    reference=bundled_reference();published=datetime(2026,9,21,tzinfo=timezone.utc)
    subject=PostSeries(UUID(int=199),next(iter(reference.account_counts)),"max",published,False,
                      (published+timedelta(hours=24),published+timedelta(hours=72,microseconds=-1)),
                      {Metric.VIEWS:(100,10000000),Metric.REACTIONS:(10,100000)})
    result=levels.assess(subject,reference=reference,analyzed_at=published+timedelta(hours=72))
    assert {11,12} <= {s.pattern for s in result.signs}
    for sign in result.signs:
        _validate(sign_payload(sign),"AnomalySignal")
    _validate(quality_payload(result.quality),"AnomalyQuality")


def test_missing_precision_is_visible_on_both_public_surfaces():
    from datetime import datetime, timezone
    row={"level":0,"analyzed_at":datetime(2026,9,28,tzinfo=timezone.utc),"signals":[],
         "quality":{"coverage":0,"summary":"нет точных данных","codes":["no_precise_metrics"],"unanalyzable":[]},
         "lag_seconds":0,"norm_version_id":None,"detector_versions":{},"review_status":"unreviewed"}
    post=analysis.analysis_body("99269506-1466-5e18-a215-a3db2688d786",12,row)
    _validate(post)
    account=analysis.levels_body("99269506-1466-5e18-a215-a3db2688d786",12,[{
        "publication_id":"99269506-1466-5e18-a215-a3db2688d786","level":0,"insufficient_data":True}])
    _validate(account,"AccountAnomalyLevels")
    assert post["levelLabel"]==account["items"][0]["levelLabel"]=="недостаточно точных данных"
    assert post["levelSymbol"]==account["items"][0]["levelSymbol"]=="·"
