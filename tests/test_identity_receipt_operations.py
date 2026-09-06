"""Keep multi-user service provisioning aligned with the strict receipt stores."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "operations"
GROUP = "m-ranked-identity-readers"


@pytest.mark.parametrize("unit", ["reverse-sync", "backup@", "restore-verify", "pitr-drill"])
def test_receipt_consumers_have_only_supplementary_read_access(unit):
    content = (ROOT / "systemd" / f"m-ranked-target-{unit}.service").read_text()
    assert f"SupplementaryGroups={GROUP}\n" in content
    assert f"\nGroup={GROUP}\n" not in content
    assert "ProtectSystem=strict\n" in content
    for line in content.splitlines():
        if line.startswith("ReadWritePaths="):
            assert "identity-receipts" not in line


@pytest.mark.parametrize("unit,leaf", [("api", "admin"), ("collector@", "collector/%i")])
def test_receipt_writers_do_not_receive_other_writers_reader_group(unit, leaf):
    content = (ROOT / "systemd" / f"m-ranked-target-{unit}.service").read_text()
    assert GROUP not in content
    assert f"-/var/lib/m-ranked/identity-receipts/{leaf}" in content
    assert "UMask=0077\n" in content


def test_all_live_receipt_participants_use_one_explicit_root():
    for name in ("api", "collector-common", "reverse-sync", "cutover"):
        content = (ROOT / "env" / f"{name}.env.example").read_text()
        values = [line.partition("=")[2] for line in content.splitlines()
                  if line.startswith("MRANKED_IDENTITY_RECEIPT_DIR=")]
        assert values == ["/var/lib/m-ranked/identity-receipts"]
