"""The research exporter must not redirect its connection outside loopback."""
import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / "research/smart-engagement-2026-09/scripts/export_local_panel.py"
spec = importlib.util.spec_from_file_location("research_export", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("dsn", ["", "dbname=anomaly_it", "host=example.org dbname=anomaly_it",
    "host=localhost hostaddr=192.0.2.1 dbname=anomaly_it", "host=localhost service=external"])
def test_export_rejects_implicit_or_remote_connections(dsn):
    with pytest.raises(ValueError, match="loopback"):
        module.local_parameters(dsn)


@pytest.mark.parametrize("host, expected", [("localhost", "127.0.0.1"), ("127.0.0.1", "127.0.0.1"), ("::1", "::1")])
def test_export_pins_loopback_address(host, expected):
    params = module.local_parameters(f"host={host} dbname=anomaly_it")
    assert params["hostaddr"] == expected
    assert params["dbname"] == "anomaly_it"
