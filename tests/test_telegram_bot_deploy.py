"""Юнит бота необязателен и ограничен; в репозитории нет значений."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
UNIT = ROOT / "operations" / "systemd" / "m-ranked-target-telegram-bot.service"
ENV = ROOT / "operations" / "env" / "telegram-bot.env.example"
RUNBOOK = ROOT / "operations" / "runbooks" / "TELEGRAM_BOT.md"
DEPLOY = ROOT / "operations" / "runbooks" / "DEPLOY.md"
ALERTS_UNIT = ROOT / "operations" / "systemd" / "m-ranked-target-alerts.service"


def unit_lines() -> list[str]:
    return [line.strip() for line in UNIT.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")]


def test_unit_is_optional_and_bounded() -> None:
    lines = unit_lines()
    assert "ConditionPathExists=/etc/m-ranked/credentials/telegram-bot-token" in lines
    assert "MemoryMax=128M" in lines
    assert "CPUQuota=20%" in lines
    assert "User=m-ranked-telegram-bot" in lines
    assert "Group=m-ranked-telegram-bot" in lines
    assert ("ExecStart=/opt/m-ranked/current/.venv/bin/python -m telegram_bot") in lines
    assert "WorkingDirectory=/opt/m-ranked/current" in lines
    assert "Restart=on-failure" in lines and "RestartSec=30" in lines


def test_unit_reads_secrets_through_credentials_only() -> None:
    lines = unit_lines()
    assert ("LoadCredential=telegram-bot-token:/etc/m-ranked/credentials/telegram-bot-token"
            in lines)
    assert "Environment=TELEGRAM_BOT_TOKEN_FILE=%d/telegram-bot-token" in lines
    assert ("LoadCredential=pgpass:/etc/m-ranked/credentials/telegram-bot-pgpass" in lines)
    assert any(line.startswith("ExecStartPre=+/usr/bin/install -m 0600") and "pgpass" in line
               for line in lines)
    assert "EnvironmentFile=-/etc/m-ranked/telegram-bot.env" in lines
    assert not any(re.search(r"TOKEN=[^%\s]|PASSWORD", line) for line in lines)


def test_unit_prepares_inbox_for_root_alerts() -> None:
    lines = unit_lines()
    install = [line for line in lines if line.startswith("ExecStartPre=+/usr/bin/install -d")]
    assert any("-m 0770" in line and "-g root" in line
               and line.endswith("/var/lib/m-ranked/telegram-bot/inbox") for line in install)
    assert any("-m 0755" in line and line.endswith(" /var/lib/m-ranked/telegram-bot")
               for line in install)
    # «-»: каталог создаёт ExecStartPre, к моменту настройки пространства имён
    # первого запуска его ещё нет (иначе status=226/NAMESPACE).
    assert "ReadWritePaths=-/var/lib/m-ranked/telegram-bot/inbox" in lines


def test_unit_is_hardened_like_other_units() -> None:
    lines = unit_lines()
    for setting in ("NoNewPrivileges=true", "ProtectSystem=strict", "ProtectHome=true",
                    "PrivateTmp=true", "PrivateDevices=true", "RestrictSUIDSGID=true",
                    "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6", "Type=simple", "Nice=10"):
        assert setting in lines, setting


def test_not_wanted_by_profiles() -> None:
    targets = list((ROOT / "operations" / "systemd").glob("*.target"))
    assert targets
    for target in targets:
        assert "telegram-bot" not in target.read_text(encoding="utf-8"), target.name
    # Включение — явный `systemctl enable` оператора; после него бот переживает
    # перезагрузку, но в цели профиля не входит.
    assert "WantedBy=multi-user.target" in unit_lines()


def test_alerts_unit_does_not_open_inet_for_telegram() -> None:
    lines = [line.strip() for line in ALERTS_UNIT.read_text(encoding="utf-8").splitlines()]
    assert "RestrictAddressFamilies=AF_UNIX" in lines
    assert "ReadWritePaths=-/var/lib/m-ranked/telegram-bot/inbox" in lines


def test_env_example_has_no_values() -> None:
    allowed = {"", "http://127.0.0.1:8080"}
    names = set()
    for raw in ENV.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, value = line.partition("=")
        names.add(name)
        assert value in allowed, name
    assert {"TELEGRAM_BOT_ADMIN_IDS", "TELEGRAM_BOT_API_BASE_URL", "TELEGRAM_BOT_DSN"} <= names


def test_runbook_exists_without_addresses_or_ids() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "m-ranked-target-telegram-bot" in text
    assert "NOLOGIN" in text and "inbox" in text and "TRAFFIC.md" in text
    assert not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text)
    assert not re.search(r"\d{6,}:[\w-]{20,}", text)  # токен BotFather
    assert not re.search(r"(?<![\w.])\d{8,}(?![\w.])", text)  # Telegram ID


def test_deploy_runbook_links_bot_runbook() -> None:
    assert "TELEGRAM_BOT.md" in DEPLOY.read_text(encoding="utf-8")


def test_bot_user_can_read_the_release_tree() -> None:
    # Релизы — root:m-ranked-release-readers 0750: без группы юнит не войдёт в
    # WorkingDirectory=/opt/m-ranked/current и не прочитает .venv.
    runbook = RUNBOOK.read_text(encoding="utf-8")
    assert ("useradd --system --no-create-home --shell /usr/sbin/nologin "
            "-G m-ranked-release-readers m-ranked-telegram-bot") in runbook
    assert ("runuser -u m-ranked-telegram-bot -- test -r "
            "/opt/m-ranked/current/telegram_bot/__main__.py") in runbook
    deploy = DEPLOY.read_text(encoding="utf-8")
    assert "usermod -a -G m-ranked-release-readers m-ranked-telegram-bot" in deploy


def test_runbook_tells_dropped_from_kept_alert_files() -> None:
    text = " ".join(RUNBOOK.read_text(encoding="utf-8").split())
    assert "копятся в `inbox` — нет получателей" not in text
    assert "нет получателей с включёнными тревогами" in text and "отбрасывает сразу" in text
    assert "Telegram недоступен" in text and "до 6 часов" in text


def test_migration_refuses_to_run_without_the_role() -> None:
    migration = (ROOT / "db" / "migrations" / "0087_telegram_bot.sql").read_text(encoding="utf-8")
    body = migration.split("BEGIN;", 1)[1]
    guard, rest = body.split("CREATE TABLE", 1)
    assert "pg_roles WHERE rolname = 'telegram_bot'" in guard
    assert "RAISE EXCEPTION" in guard and "operations/runbooks/DEPLOY.md" in guard
    assert not re.search(r"^\s*(GRANT|CREATE)\b", guard, re.M)   # только проверка, ничего не создаёт
