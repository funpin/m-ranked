from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "operations" / "systemd"


def text(name: str) -> str:
    return (SYSTEMD / name).read_text(encoding="utf-8")


def dependencies(name: str) -> set[str]:
    result: set[str] = set()
    for line in text(name).splitlines():
        if line.startswith(("Requires=", "Wants=")):
            result.update(line.split("=", 1)[1].split())
    return result


def test_profile_a_target_is_complete_single_host_runtime() -> None:
    assert {
        "m-ranked-target-api.service",
        "m-ranked-target-web.service",
        "m-ranked-target-collector@telegram.service",
        "m-ranked-target-collector@vk.service",
        "m-ranked-target-collector@max.service",
        "m-ranked-target-collector@rutube.service",
        "m-ranked-target-collector-watchdog.timer",
        "m-ranked-target-web-cache-gc.timer",
        "m-ranked-target-anomaly-analysis.service",
        "m-ranked-target-anomaly-norms.timer",
        "m-ranked-target-maintenance.timer",
        "m-ranked-target-official-rating.timer",
        "m-ranked-target-overview-metrics.timer",
    } <= dependencies("m-ranked-target.target")


def test_profile_b_targets_split_collection_and_presentation() -> None:
    server1 = dependencies("m-ranked-target-profile-b-server1.target")
    server2 = dependencies("m-ranked-target-profile-b-server2.target")
    assert {
        "m-ranked-target-collector@telegram.service",
        "m-ranked-target-collector@vk.service",
        "m-ranked-target-collector@max.service",
        "m-ranked-target-collector@rutube.service",
        "m-ranked-target-collector-watchdog.timer",
        "m-ranked-target-collectors.slice",
    } <= server1
    assert {
        "m-ranked-target-api.service",
        "m-ranked-target-web.service",
        "m-ranked-target-web-cache-gc.timer",
        "m-ranked-target-transfer-ingest.service",
        "m-ranked-target-cache-warmup.service",
        "m-ranked-target-redis.service",
        "m-ranked-target-anomaly-analysis.service",
        "m-ranked-target-anomaly-norms.timer",
        "m-ranked-target-maintenance.timer",
        "m-ranked-target-official-rating.timer",
        "m-ranked-target-overview-metrics.timer",
    } <= server2
    assert not any("collector@" in unit for unit in server2)
    assert not any(unit in server1 for unit in {"m-ranked-target-api.service", "m-ranked-target-web.service"})
    assert "Conflicts=m-ranked-target.target" in text("m-ranked-target-profile-b-server1.target")
    assert "Conflicts=m-ranked-target.target" in text("m-ranked-target-profile-b-server2.target")


def test_redis_is_optional_to_api() -> None:
    api = text("m-ranked-target-api.service")
    assert "Redis" not in "\n".join(
        line for line in api.splitlines() if line.startswith(("After=", "Requires="))
    )
    target = text("m-ranked-target-profile-b-server2.target")
    assert "Wants=m-ranked-target-redis.service" in target
    assert "Requires=m-ranked-target-redis.service" not in target


def test_new_services_keep_hardening_and_bounds() -> None:
    required = {
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "CapabilityBoundingSet=",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "MemoryMax=",
        "TasksMax=",
    }
    for name in (
        "m-ranked-target-transfer-ingest.service",
        "m-ranked-target-cache-warmup.service",
        "m-ranked-target-redis.service",
        "m-ranked-target-anomaly-analysis.service",
        "m-ranked-target-anomaly-norms.service",
    ):
        unit = text(name)
        for directive in required:
            assert directive in unit, (name, directive)


def test_profile_b_network_exceptions_are_narrow() -> None:
    collector = text("m-ranked-target-collector@.service")
    assert "IPAddressDeny=10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10" in collector
    dropin = (SYSTEMD / "profile-b-server1" / "m-ranked-target-collector@.service.d" / "20-transfer-network.conf.example").read_text()
    assert "IPAddressAllow=192.0.2.20/32" in dropin
    assert "IPAddressDeny=" not in dropin
    ingest = text("m-ranked-target-transfer-ingest.service")
    assert "IPAddressDeny=any" in ingest
    assert "IPAddressAllow=localhost" in ingest


def test_cache_warmup_uses_internal_schedule_and_pid_metrics_are_cleaned() -> None:
    assert not (SYSTEMD / "m-ranked-target-cache-warmup.timer").exists()
    warmup = text("m-ranked-target-cache-warmup.service")
    assert "python -m api.cache_warmup" in warmup
    assert "API_CACHE_WARMUP_INTERVAL_SECONDS" in (ROOT / "operations" / "env" / "api-profile-b.env.example").read_text()
    api = text("m-ranked-target-api.service")
    assert "m-ranked-api-cache-*.prom -delete" in api


def test_collector_stop_window_exceeds_grace() -> None:
    assert "TimeoutStopSec=60s" in text("m-ranked-target-collector@.service")
    common = (ROOT / "operations" / "env" / "collector-common.env.example").read_text()
    assert "COLLECTOR_SHUTDOWN_GRACE_SECONDS=45" in common


def test_runtime_configuration_contract() -> None:
    subprocess.run(
        [str(ROOT / "operations" / "scripts" / "check-runtime-config.py")],
        cwd=ROOT,
        check=True,
    )


def test_anomaly_units_keep_the_server_two_budget() -> None:
    # Работнику — 384 МиБ круглосуточно; ночному заданию норм — 768: оно держит
    # ряды всех аккаунтов площадки и на реальных данных упёрлось в 384.
    for name, memory in (("m-ranked-target-anomaly-analysis.service", "MemoryMax=384M"),
                         ("m-ranked-target-anomaly-norms.service", "MemoryMax=768M")):
        unit = text(name)
        for directive in ("CPUQuota=50%", memory, "Nice=10"):
            assert directive in unit, (name, directive)
    assert "python -m anomaly_analysis.norms_job" in text("m-ranked-target-anomaly-norms.service")
    # Каталог выполнения удаляется при остановке юнита: у задания он свой.
    assert "RuntimeDirectory=m-ranked-anomaly-norms" in text("m-ranked-target-anomaly-norms.service")
    assert "RuntimeDirectory=m-ranked-anomaly\n" in text("m-ranked-target-anomaly-analysis.service")
    timer = text("m-ranked-target-anomaly-norms.timer")
    assert "Europe/Moscow" in timer and "RandomizedDelaySec=" in timer


def test_installer_ships_the_anomaly_units_where_the_full_history_lives() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("installer", ROOT / "operations" / "install" / "install.py")
    installer = importlib.util.module_from_spec(spec)
    import sys
    sys.path.insert(0, str(ROOT / "operations" / "install"))
    try:
        spec.loader.exec_module(installer)
    finally:
        sys.path.remove(str(ROOT / "operations" / "install"))
    for name in installer.UNITS_ANOMALY + installer.UNITS_SERVER2 + installer.UNITS_COMMON_PRESENTATION:
        assert (SYSTEMD / name).is_file(), name
    assert set(installer.UNITS_ANOMALY) <= set(installer.UNITS_SERVER2)
    assert "m-ranked-target-anomaly-norms.timer" in installer.UNITS_ANOMALY
