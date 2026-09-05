from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from .model import SourceInventory


def write_reports(
    report_dir: Path,
    stem: str,
    payload: Mapping[str, Any],
) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / f"{stem}.json"
    markdown_path = report_dir / f"{stem}.md"
    json_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(_markdown_report(payload), encoding="utf-8")
    return json_path, markdown_path


def inventory_payload(inventory: SourceInventory) -> dict[str, Any]:
    return {
        "report_version": 1,
        "report_type": "source-inventory",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gate": {
            "status": (
                "pass"
                if inventory.quick_check == "ok" and not inventory.foreign_key_violations
                else "fail"
            ),
            "critical_mismatches": inventory.foreign_key_violations,
        },
        "source": inventory.as_dict(),
    }


def _markdown_report(payload: Mapping[str, Any]) -> str:
    lines = [
        "# M-Ranked migration reconciliation",
        "",
        f"- Report type: `{payload.get('report_type', 'unknown')}`",
        f"- Generated: `{payload.get('generated_at', 'unknown')}`",
    ]
    gate = payload.get("gate")
    if isinstance(gate, Mapping):
        lines.extend(
            [
                f"- Gate: **{gate.get('status', 'unknown')}**",
                f"- Critical mismatches: `{gate.get('critical_mismatches', 'unknown')}`",
            ]
        )
    source = payload.get("source")
    if isinstance(source, Mapping):
        lines.extend(
            [
                "",
                "## Source",
                "",
                f"- File: `{source.get('source_path')}`",
                f"- SHA-256: `{source.get('source_sha256')}`",
                f"- SQLite schema: `{source.get('schema_version')}`",
                f"- Quick check: `{source.get('quick_check')}`",
                f"- FK violations: `{source.get('foreign_key_violations')}`",
                "",
                "## Tables",
                "",
                "| Table | Rows | Canonical SHA-256 | Min time | Max time |",
                "|---|---:|---|---|---|",
            ]
        )
        for table in source.get("tables", []):
            lines.append(
                "| {name} | {row_count} | `{canonical_hash}` | {min_timestamp} | "
                "{max_timestamp} |".format(**table)
            )
        lines.extend(["", "## Metric/quality totals", ""])
        for key, value in sorted(dict(source.get("totals", {})).items()):
            lines.append(f"- `{key}`: `{value}`")
    stats = payload.get("bridge")
    if isinstance(stats, Mapping):
        lines.extend(["", "## Import", ""])
        for key, value in stats.items():
            lines.append(f"- `{key}`: `{value}`")
    mismatches = payload.get("mismatches")
    if isinstance(mismatches, list):
        lines.extend(["", "## Mismatches", ""])
        if not mismatches:
            lines.append("None.")
        for mismatch in mismatches:
            lines.append(f"- `{json.dumps(mismatch, ensure_ascii=False, sort_keys=True)}`")
    lines.append("")
    return "\n".join(lines)
