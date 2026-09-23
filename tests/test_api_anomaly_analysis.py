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


def _validate(body: dict) -> None:
    registry = Registry().with_resource("urn:contract", Resource.from_contents(CONTRACT, default_specification=DRAFT202012))
    schema = {"$ref": "urn:contract#/components/schemas/PublicationAnomalyAnalysis"}
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


def test_api_level_words_match_the_analysis_module_and_the_glossary():
    assert analysis.LEVEL_LABELS == levels.LEVEL_LABELS
    assert analysis.LEVEL_SYMBOLS == levels.LEVEL_SYMBOLS
    for text in (*analysis.LEVEL_LABELS.values(), analysis.DISCLAIMER, analysis.NOT_ANALYZED):
        assert not any(word in text.lower() for word in FORBIDDEN), text


def test_analysis_cache_is_not_invalidated_by_ingestion():
    assert analysis.ANALYSIS_TAGS == frozenset({"analysis"})
