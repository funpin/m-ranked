from __future__ import annotations

from dataclasses import dataclass

from .domain import Abstained, DetectorOutcome, Finding, Severity, severity_for

AGGREGATOR_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class AggregateResult:
    suspicion_score: float | None
    severity: Severity | None
    contributing_indexes: tuple[int, ...]
    evaluated_count: int
    abstained_count: int
    status: str


def aggregate(outcomes: tuple[DetectorOutcome, ...]) -> AggregateResult:
    findings = tuple((index, item) for index, item in enumerate(outcomes) if isinstance(item, Finding))
    abstained = sum(isinstance(item, Abstained) for item in outcomes)
    evaluated = len(outcomes) - abstained
    if findings:
        score = max(item.score for _, item in findings)
        contributing = tuple(index for index, item in findings if item.score == score)
        return AggregateResult(score, severity_for(score), contributing, evaluated, abstained,
                               "partial" if abstained else "ready")
    if evaluated:
        return AggregateResult(0.0, Severity.LOW, (), evaluated, abstained,
                               "partial" if abstained else "ready")
    return AggregateResult(None, None, (), 0, abstained, "partial")
