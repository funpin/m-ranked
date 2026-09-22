"""Проверки окружения перед установкой.

Каждая проверка отвечает на один вопрос и возвращает результат, который можно
показать человеку. Установщик не чинит окружение сам: он говорит, что не так,
и чем это чинится. Молчаливая доустановка пакетов на чужом сервере — худший
вид сюрприза.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


OK = "ok"
WARN = "warn"
FAIL = "fail"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: str
    detail: str
    remedy: str = ""


def _run(*args: str) -> str:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def check_root() -> Check:
    if os.geteuid() == 0:
        return Check("права", OK, "выполняется от root")
    return Check(
        "права", FAIL, "нужен root",
        "перезапустите под sudo: sudo python3 operations/install/install.py",
    )


def check_systemd() -> Check:
    version = _run("systemctl", "--version").splitlines()
    if not version:
        return Check("systemd", FAIL, "не найден", "требуется система с systemd")
    number = version[0].split()[1] if len(version[0].split()) > 1 else "?"
    # 257 отдаёт credential как 0440 root:root, 252 — как 0400 во владении
    # службы. Юниты рассчитаны на обе, но знать версию полезно при разборе.
    return Check("systemd", OK, f"версия {number}")


def check_python() -> Check:
    major, minor = sys.version_info[:2]
    detail = f"{major}.{minor}"
    if (major, minor) < (3, 11):
        return Check(
            "python", FAIL, detail + " — слишком старый",
            "нужен Python 3.11 или новее",
        )
    return Check("python", OK, detail)


def check_venv_module() -> Check:
    try:
        import ensurepip  # noqa: F401
    except ImportError:
        return Check(
            "python venv", FAIL, "нет модуля ensurepip",
            "apt-get install -y python3-venv python3-pip",
        )
    return Check("python venv", OK, "доступен")


def check_docker() -> Check:
    if shutil.which("docker") is None:
        return Check(
            "docker", FAIL, "не найден",
            "база и часть служб запускаются контейнерами; установите docker",
        )
    version = _run("docker", "--version")
    compose = _run("docker", "compose", "version")
    if not compose:
        return Check(
            "docker", FAIL, "нет docker compose",
            "установите плагин docker-compose-plugin",
        )
    return Check("docker", OK, version.replace("Docker version ", ""))


def check_node(required_major: int = 24) -> Check:
    if shutil.which("node") is None:
        return Check(
            "node", FAIL, "не найден",
            f"фронтенд требует Node {required_major}+; "
            "поставьте из nodejs.org и дайте ссылку /usr/bin/node",
        )
    raw = _run("node", "--version").lstrip("v")
    major = int(raw.split(".")[0]) if raw and raw[0].isdigit() else 0
    if major < required_major:
        return Check(
            "node", FAIL, f"{raw} — старее требуемого",
            f"нужен Node {required_major}+",
        )
    return Check("node", OK, raw)


def check_disk(path: str = "/", need_gib: int = 20) -> Check:
    usage = shutil.disk_usage(path)
    free = usage.free / (1024 ** 3)
    detail = f"свободно {free:.1f} ГиБ из {usage.total / (1024 ** 3):.0f}"
    if free < need_gib:
        return Check(
            "диск", WARN, detail,
            f"рекомендуется не меньше {need_gib} ГиБ: база, снимок и три "
            "резервные копии живут на одном томе",
        )
    return Check("диск", OK, detail)


def check_memory(need_mib: int = 1800) -> Check:
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return Check("память", WARN, "не удалось прочитать /proc/meminfo")
    total_kib = 0
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            total_kib = int(line.split()[1])
            break
    total_mib = total_kib // 1024
    detail = f"{total_mib} МиБ"
    if total_mib < need_mib:
        return Check(
            "память", WARN, detail,
            f"рекомендуется не меньше {need_mib} МиБ",
        )
    return Check("память", OK, detail)


def check_port_free(port: int, label: str) -> Check:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return Check(
                f"порт {port}", WARN, f"занят ({label})",
                "выберите другой порт в файле окружения; "
                "установщик спросит его ниже",
            )
    return Check(f"порт {port}", OK, "свободен")


def check_timezone() -> Check:
    zone = _run("timedatectl", "show", "-p", "Timezone", "--value")
    if not zone:
        return Check("часовой пояс", WARN, "не удалось определить")
    if zone != "Europe/Moscow":
        return Check(
            "часовой пояс", WARN, zone,
            "все измерения и журналы проекта ведутся по Москве: "
            "timedatectl set-timezone Europe/Moscow",
        )
    return Check("часовой пояс", OK, zone)


def check_openssl() -> Check:
    if shutil.which("openssl") is None:
        return Check(
            "openssl", FAIL, "не найден",
            "нужен для выпуска сертификатов переноса",
        )
    return Check("openssl", OK, _run("openssl", "version"))


def for_profile(profile: str) -> list[Check]:
    """Набор проверок под выбранный способ установки."""
    common = [check_root(), check_systemd(), check_python(), check_venv_module(),
              check_disk(), check_memory(), check_timezone()]
    if profile == "a":
        return common + [check_docker(), check_node(), check_port_free(5432, "postgres")]
    if profile == "b-server1":
        return common + [check_docker(), check_openssl()]
    if profile == "b-server2":
        return common + [
            check_docker(), check_node(), check_openssl(),
            check_port_free(6379, "redis"), check_port_free(8443, "приёмник"),
        ]
    raise ValueError(f"неизвестный профиль: {profile}")
