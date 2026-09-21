"""Compare collect/persist ceilings over a simulated day.

Pure simulation: no database and no provider. Inputs are the audited p50
cycle durations split into their network and write halves, so the output
answers one question only — what does raising the ceiling buy, and what does
it cost in waiting for the write lock.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector_target.model import Platform
from collector_target.phase import (
    MAX_COLLECT_SLOTS, PhasePolicy, max_overlap, simulate_split_phases,
)

# Audited p50 durations, split. The write half is derived from the sealing
# probe: ~23 SQL round trips per account batch is roughly a tenth of a cycle.
COLLECT = {
    Platform.TELEGRAM: 84, Platform.VK: 121, Platform.MAX: 84, Platform.RUTUBE: 620,
}
PERSIST = {
    Platform.TELEGRAM: 9, Platform.VK: 13, Platform.MAX: 9, Platform.RUTUBE: 70,
}
POLICIES = {
    Platform.TELEGRAM: PhasePolicy(Platform.TELEGRAM, 300, 0, 900),
    Platform.VK: PhasePolicy(Platform.VK, 300, 75, 600),
    Platform.MAX: PhasePolicy(Platform.MAX, 300, 150, 600),
    Platform.RUTUBE: PhasePolicy(Platform.RUTUBE, 3600, 225, 1800),
}
DESIRED = {"telegram": 288, "vk": 288, "max": 288, "rutube": 24}


def main() -> int:
    start = datetime(2026, 9, 22, tzinfo=timezone.utc)
    ceilings = {}
    for slots in range(1, MAX_COLLECT_SLOTS + 1):
        phases = simulate_split_phases(
            POLICIES, COLLECT, PERSIST, start=start, hours=24, collect_slots=slots,
        )
        waits = sorted(item.persist_wait_seconds for item in phases)
        counts = {
            platform.value: sum(1 for item in phases if item.platform == platform)
            for platform in Platform
        }
        ceilings[str(slots)] = {
            "phases": len(phases),
            "counts": counts,
            "servedFractionOfDesired": {
                name: round(counts[name] / DESIRED[name], 3) for name in counts
            },
            "maxPersistOverlap": max_overlap(
                [(item.persist_started, item.persist_finished) for item in phases]
            ),
            "maxCollectOverlap": max_overlap(
                [(item.collect_started, item.persist_finished) for item in phases]
            ),
            "persistWaitP50Seconds": waits[len(waits) // 2],
            "persistWaitP95Seconds": waits[int(len(waits) * 0.95)],
            "persistWaitMaxSeconds": waits[-1],
        }
    print(json.dumps({"hours": 24, "ceilings": ceilings}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
