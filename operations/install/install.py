#!/usr/bin/env python3
"""Установщик m-ranked с текстовым интерфейсом.

Поддерживает оба способа развёртывания:

    A          всё на одном сервере;
    B/сервер-1 сборщики и рабочий набор данных;
    B/сервер-2 web, API, аналитика и приёмник данных.

Интерфейс намеренно текстовый, без curses и без внешних зависимостей: его
запускают по ssh на свежей машине, где нет ничего, кроме системного Python.

Установщик идемпотентен. Он не перевыпускает секреты, которые уже выданы, и
не переписывает файлы окружения, которые уже правил оператор: в обоих случаях
он говорит, что оставил как есть.

Запуск:
    sudo python3 operations/install/install.py
    sudo python3 operations/install/install.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import preflight  # noqa: E402
import steps  # noqa: E402
from steps import Context  # noqa: E402


RELEASE = HERE.parent.parent
ENV_EXAMPLES = RELEASE / "operations" / "env"

PROFILES = {
    "1": ("a", "Профиль A — всё на одном сервере"),
    "2": ("b-server1", "Профиль B, Сервер 1 — сборщики"),
    "3": ("b-server2", "Профиль B, Сервер 2 — web, API и аналитика"),
}

COLLECTOR_PLATFORMS = ("telegram", "vk", "max", "rutube")

DB_ROLES = (
    "migration_owner", "api_read", "api_write_admin", "collector_ingest",
    "backup", "maintenance", "analytics_worker", "outbox_worker",
)


# --- интерфейс --------------------------------------------------------------

def rule(title: str = "") -> None:
    if title:
        print(f"\n\033[1m{title}\033[0m")
        print("─" * max(len(title), 40))
    else:
        print("─" * 40)


def ask(question: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"  {question}{suffix}: ").strip()
        if answer:
            return answer
        if default:
            return default
        print("    значение обязательно")


def ask_yes(question: str, default: bool = True) -> bool:
    hint = "Д/н" if default else "д/Н"
    answer = input(f"  {question} [{hint}]: ").strip().lower()
    if not answer:
        return default
    return answer in ("д", "da", "y", "yes", "да")


def show_checks(checks: list[preflight.Check]) -> bool:
    marks = {preflight.OK: "  ✓", preflight.WARN: "  !", preflight.FAIL: "  ✗"}
    blocking = False
    for check in checks:
        print(f"{marks[check.status]} {check.name}: {check.detail}")
        if check.remedy:
            print(f"      {check.remedy}")
        if check.status == preflight.FAIL:
            blocking = True
    return not blocking


def choose_profile() -> str:
    rule("Способ установки")
    for key, (_, title) in PROFILES.items():
        print(f"  {key}. {title}")
    while True:
        choice = input("\n  номер: ").strip()
        if choice in PROFILES:
            return PROFILES[choice][0]
        print("    выберите 1, 2 или 3")


# --- общие шаги -------------------------------------------------------------

def base_layout(context: Context) -> None:
    rule("Каталоги и общие учётные записи")
    steps.ensure_directory(context, steps.ETC, 0o755)
    # Каталог должен быть проходимым: службы читают свои конфиги уже после
    # сброса прав. Секреты защищены правами самих файлов.
    steps.ensure_directory(context, steps.CREDENTIALS, 0o750)
    steps.ensure_directory(context, steps.STATE, 0o711)
    steps.ensure_group(context, "node-exporter")
    steps.ensure_directory(
        context, Path("/var/lib/node_exporter/textfile_collector"),
        0o775, owner="root", group="node-exporter",
    )


def database_secrets(context: Context) -> dict[str, str]:
    """Пароли ролей базы. Уже существующие не трогаются."""
    rule("Секреты ролей базы")
    values: dict[str, str] = {}
    for role in DB_ROLES:
        path = steps.CREDENTIALS / f"{role.replace('_', '-')}-db-password"
        if path.exists():
            values[role] = path.read_text(encoding="utf-8").strip()
            context.note(f"пароль роли {role} уже есть")
            continue
        secret = steps.password()
        steps.write_secret(context, path, secret)
        values[role] = secret
    return values


def collector_users(context: Context) -> None:
    for platform in COLLECTOR_PLATFORMS:
        user = f"m-ranked-collector-{platform}"
        steps.ensure_user(context, user)
        steps.ensure_directory(
            context, steps.STATE / "collectors" / platform, 0o700,
            owner=user, group=user,
        )
        steps.ensure_directory(
            context, steps.STATE / "collectors" / platform / "raw-evidence", 0o700,
            owner=user, group=user,
        )
    steps.ensure_directory(context, steps.STATE / "identity-receipts", 0o755)
    steps.ensure_directory(context, steps.STATE / "identity-receipts" / "collector", 0o755)
    for platform in COLLECTOR_PLATFORMS:
        user = f"m-ranked-collector-{platform}"
        steps.ensure_directory(
            context, steps.STATE / "identity-receipts" / "collector" / platform,
            0o700, owner=user, group=user,
        )


def presentation_users(context: Context) -> None:
    for user in ("m-ranked-api", "m-ranked-web", "m-ranked-maintenance"):
        steps.ensure_user(context, user)
    context.run("usermod", "-aG", "node-exporter", "m-ranked-api", check=False)
    steps.ensure_directory(
        context, steps.STATE / "api", 0o700, owner="m-ranked-api", group="m-ranked-api")
    steps.ensure_directory(
        context, steps.STATE / "web-cache", 0o700,
        owner="m-ranked-web", group="m-ranked-web")
    steps.ensure_directory(context, steps.STATE / "identity-receipts", 0o755)
    steps.ensure_directory(
        context, steps.STATE / "identity-receipts" / "admin", 0o700,
        owner="m-ranked-api", group="m-ranked-api")


def admin_credentials(context: Context) -> None:
    """Учётные данные админки. Хеш пароля и TOTP задаёт оператор."""
    rule("Админка")
    users_file = steps.CREDENTIALS / "admin-auth-users.json"
    if users_file.exists():
        context.note("учётные записи админки уже настроены")
    else:
        print("  Файл учётных записей админки заполняется отдельно: он содержит")
        print("  bcrypt-хеш пароля и секрет одноразовых кодов. Установщик")
        print("  создаёт пустой список — заполните до первого входа.")
        steps.write_secret(context, users_file, "[]")
    secret_file = steps.CREDENTIALS / "admin-csrf-secret"
    if not secret_file.exists():
        steps.write_secret(context, secret_file, steps.password(64))


# --- профиль A --------------------------------------------------------------

UNITS_COMMON_PRESENTATION = [
    "m-ranked-target-api.service",
    "m-ranked-target-web.service",
    "m-ranked-target-web-cache-gc.service",
    "m-ranked-target-web-cache-gc.timer",
    "m-ranked-target-maintenance.service",
    "m-ranked-target-maintenance.timer",
    "m-ranked-target-official-rating.service",
    "m-ranked-target-official-rating.timer",
    "m-ranked-target-overview-metrics.service",
    "m-ranked-target-overview-metrics.timer",
    "m-ranked-target-dump-backup.service",
    "m-ranked-target-dump-backup.timer",
]

UNITS_COLLECTORS = [
    "m-ranked-target-collector@.service",
    "m-ranked-target-collectors.slice",
    "m-ranked-target-collector-watchdog.service",
    "m-ranked-target-collector-watchdog.timer",
]


def install_profile_a(context: Context) -> list[str]:
    rule("Профиль A — всё на одном сервере")
    port = context.answers["api_port"]
    base_layout(context)
    presentation_users(context)
    collector_users(context)
    secrets = database_secrets(context)
    admin_credentials(context)

    rule("Окружение")
    steps.render_env(
        context, ENV_EXAMPLES / "api.env.example", steps.ETC / "api.env",
        {
            "SERVER_PORT": port,
            "API_DEPLOYMENT_PROFILE": "a",
            "API_WORKERS": "1",
            "ADMIN_EXPECTED_ORIGIN": f"https://{context.answers['domain']}",
            "APP_BUILD_ID": context.release.name,
        },
        mode=0o640,
    )
    steps.render_env(
        context, ENV_EXAMPLES / "web.env.example", steps.ETC / "web.env",
        {"API_BASE_URL": f"http://127.0.0.1:{port}"}, mode=0o640,
    )
    for name in ("api-read", "api-write-admin", "outbox-worker"):
        role = name.replace("-", "_")
        steps.write_pgpass(context, f"{name}-pgpass", role, secrets.get(role, ""))
    steps.write_pgpass(
        context, "maintenance-pgpass", "maintenance", secrets.get("maintenance", ""))

    rule("Юниты")
    units = UNITS_COMMON_PRESENTATION + UNITS_COLLECTORS + ["m-ranked-target.target"]
    steps.install_units(context, units)
    steps.daemon_reload(context)
    return units


# --- профиль B, сервер 1 ----------------------------------------------------

def install_profile_b_server1(context: Context) -> list[str]:
    rule("Профиль B, Сервер 1 — сборщики")
    base_layout(context)
    collector_users(context)
    steps.ensure_user(context, "m-ranked-transfer-sender")
    secrets = database_secrets(context)

    rule("Перенос на Сервер 2")
    endpoint = context.answers["ingest_endpoint"]
    producer = context.answers["producer_id"]
    print("  Клиентский сертификат и удостоверяющий центр выпускает Сервер 2.")
    print("  Скопируйте оттуда три файла и положите рядом с установщиком:")
    print(f"    {producer}.crt, {producer}.key, transfer-ca.crt")
    source = Path(context.answers["pki_source"])
    for origin, name in (
        (source / f"{producer}.crt", "transfer-client.crt"),
        (source / f"{producer}.key", "transfer-client.key"),
        (source / "transfer-ca.crt", "transfer-ca.crt"),
    ):
        steps.place_credential(context, origin, name)

    steps.render_env(
        context, ENV_EXAMPLES / "collector-profile-b.env.example",
        steps.ETC / "collector-profile.env",
        {
            "COLLECTOR_TRANSFER_HTTPS_ENDPOINT": endpoint,
            "COLLECTOR_TRANSFER_PRODUCER_ID": producer,
            "COLLECTOR_COLLECT_CONCURRENCY": context.answers["collect_concurrency"],
        },
    )
    steps.render_env(
        context, ENV_EXAMPLES / "transfer-sender.env.example",
        steps.ETC / "transfer-sender.env",
        {"COLLECTOR_TRANSFER_PRODUCER_ID": producer},
    )
    steps.write_pgpass(
        context, "transfer-sender-pgpass", "outbox_worker",
        secrets.get("outbox_worker", ""))

    rule("Юниты")
    units = UNITS_COLLECTORS + [
        "m-ranked-target-transfer-sender.service",
        "m-ranked-target-profile-b-server1.target",
    ]
    steps.install_units(context, units)
    steps.install_dropins(
        context, "profile-b-server1", {"192.0.2.20": context.answers["ingest_host"]})
    steps.daemon_reload(context)
    return units


# --- профиль B, сервер 2 ----------------------------------------------------

UNITS_SERVER2 = UNITS_COMMON_PRESENTATION + [
    "m-ranked-target-redis.service",
    "m-ranked-target-transfer-ingest.service",
    "m-ranked-target-cache-warmup.service",
    "m-ranked-target-profile-b-server2.target",
]


def install_profile_b_server2(context: Context) -> list[str]:
    rule("Профиль B, Сервер 2 — web, API и аналитика")
    port = context.answers["api_port"]
    base_layout(context)
    presentation_users(context)
    for user in ("m-ranked-redis", "m-ranked-transfer-ingest", "m-ranked-cache-warmup"):
        steps.ensure_user(context, user)
    secrets = database_secrets(context)
    admin_credentials(context)

    rule("Каталоги приёмника")
    ingest_root = steps.STATE / "transfer-ingest"
    steps.ensure_directory(
        context, ingest_root, 0o700,
        owner="m-ranked-transfer-ingest", group="m-ranked-transfer-ingest")
    steps.ensure_directory(
        context, ingest_root / "raw-evidence", 0o700,
        owner="m-ranked-transfer-ingest", group="m-ranked-transfer-ingest")
    steps.ensure_directory(
        context, ingest_root / "identity-receipts", 0o755,
        owner="m-ranked-transfer-ingest", group="m-ranked-transfer-ingest")
    steps.ensure_directory(
        context, ingest_root / "identity-receipts" / "collector", 0o755,
        owner="m-ranked-transfer-ingest", group="m-ranked-transfer-ingest")
    for platform in COLLECTOR_PLATFORMS:
        steps.ensure_directory(
            context, ingest_root / "identity-receipts" / "collector" / platform,
            0o700, owner="m-ranked-transfer-ingest",
            group="m-ranked-transfer-ingest")

    rule("Удостоверяющий центр переноса")
    steps.issue_transfer_ca(context)
    steps.issue_server_certificate(context, context.answers["ingest_host"])
    producers = [p.strip() for p in context.answers["producers"].split(",") if p.strip()]
    for producer in producers:
        steps.issue_client_certificate(context, producer)
    for origin, name in (
        (steps.PKI / "transfer-server.crt", "transfer-server.crt"),
        (steps.PKI / "transfer-server.key", "transfer-server.key"),
        (steps.PKI / "transfer-ca.crt", "transfer-ca.crt"),
    ):
        steps.place_credential(context, origin, name)

    rule("Redis")
    redis_password = steps.password()
    acl = steps.CREDENTIALS / "redis.acl"
    if not acl.exists():
        steps.write_secret(
            context, acl,
            "user default off\n"
            f"user mranked on >{redis_password} ~mranked:response:v1:* "
            "+get +set +del +mget +zadd +zcard +zpopmin +zrem "
            "+zremrangebyscore +zrangebyscore +eval +multi +exec +ping",
        )
        steps.write_secret(
            context, steps.CREDENTIALS / "redis-url",
            f"redis://mranked:{redis_password}@127.0.0.1:6379/0",
        )
    if not (steps.ETC / "redis.conf").exists() and not context.dry_run:
        import shutil as _shutil
        _shutil.copy2(
            context.release / "operations" / "redis" / "m-ranked.conf",
            steps.ETC / "redis.conf")
        (steps.ETC / "redis.conf").chmod(0o644)
        context.note("установлен redis.conf")

    rule("Окружение")
    steps.render_env(
        context, ENV_EXAMPLES / "api.env.example", steps.ETC / "api.env",
        {
            "SERVER_PORT": port,
            "ADMIN_EXPECTED_ORIGIN": f"https://{context.answers['domain']}",
            "APP_BUILD_ID": context.release.name,
        },
        mode=0o640,
    )
    steps.render_env(
        context, ENV_EXAMPLES / "api-profile-b.env.example",
        steps.ETC / "api-profile.env",
        {
            "API_WORKERS": context.answers["api_workers"],
            "API_CACHE_WARMUP_BASE_URL": f"http://127.0.0.1:{port}",
        },
        mode=0o640,
    )
    steps.render_env(
        context, ENV_EXAMPLES / "cache-warmup.env.example",
        steps.ETC / "cache-warmup.env",
        {"API_CACHE_WARMUP_BASE_URL": f"http://127.0.0.1:{port}"},
    )
    steps.render_env(
        context, ENV_EXAMPLES / "web.env.example", steps.ETC / "web.env",
        {"API_BASE_URL": f"http://127.0.0.1:{port}"}, mode=0o640,
    )
    steps.render_env(
        context, ENV_EXAMPLES / "transfer-ingest.env.example",
        steps.ETC / "transfer-ingest.env",
        {
            "TRANSFER_INGEST_HOST": context.answers["ingest_host"],
            "TRANSFER_INGEST_ALLOWED_PRODUCERS": ",".join(producers),
        },
    )
    for name in ("api-read", "api-write-admin", "outbox-worker"):
        role = name.replace("-", "_")
        steps.write_pgpass(context, f"{name}-pgpass", role, secrets.get(role, ""))
    steps.write_pgpass(
        context, "maintenance-pgpass", "maintenance", secrets.get("maintenance", ""))
    steps.write_pgpass(
        context, "transfer-ingest-pgpass", "collector_ingest",
        secrets.get("collector_ingest", ""))

    rule("Юниты")
    steps.install_units(context, UNITS_SERVER2)
    steps.install_dropins(
        context, "profile-b-server2",
        {"192.0.2.10": context.answers.get("collector_hosts", "192.0.2.10")})
    steps.daemon_reload(context)
    return UNITS_SERVER2


# --- вопросы ----------------------------------------------------------------

def questions(profile: str) -> dict[str, str]:
    rule("Параметры")
    answers: dict[str, str] = {}
    if profile in ("a", "b-server2"):
        answers["domain"] = ask("домен сайта", "m.funpin.org")
        answers["api_port"] = ask("порт API на петлевом интерфейсе", "8080")
    if profile == "b-server2":
        answers["api_workers"] = ask("воркеров API (по числу ядер)", "2")
        answers["ingest_host"] = ask("адрес, на котором слушает приёмник")
        answers["producers"] = ask("идентификаторы серверов-сборщиков через запятую", "server-1")
        answers["collector_hosts"] = ask("адрес Сервера 1 для firewall (/32)")
    if profile == "b-server1":
        answers["producer_id"] = ask("идентификатор этого сборщика", "server-1")
        answers["ingest_host"] = ask("адрес Сервера 2")
        answers["ingest_endpoint"] = ask(
            "адрес приёмника",
            f"https://{answers['ingest_host']}:8443/transfer/v1/batches")
        answers["collect_concurrency"] = ask(
            "одновременных фаз сбора (1–4; запись всё равно одна)", "2")
        answers["pki_source"] = ask(
            "каталог с сертификатами, скопированными с Сервера 2", "/root/pki")
    return answers


def next_steps(profile: str, context: Context) -> None:
    rule("Что осталось сделать руками")
    print("  Установщик не делает того, что должно быть решением человека.")
    if profile in ("a", "b-server2"):
        print("  • поднять PostgreSQL и применить db/migrations по порядку имён;")
        print("  • выдать ролям пароли из /etc/m-ranked/credentials;")
        print("  • собрать фронтенд: pnpm install && pnpm build,")
        print("    затем operations/scripts/finalize-web-release.sh <релиз>;")
        print("  • положить vhost из operations/nginx и выпустить сертификат;")
        print("  • заполнить admin-auth-users.json до первого входа в админку.")
    if profile == "b-server2":
        print(f"  • открыть порт приёмника только для Сервера 1:")
        print(f"      ip saddr {context.answers.get('collector_hosts')} "
              "tcp dport 8443 accept")
        print("  • передать на Сервер 1 файлы из /etc/m-ranked/pki:")
        print("      <producer>.crt, <producer>.key, transfer-ca.crt")
    if profile in ("a", "b-server1"):
        print("  • поставить клиент MAX отдельной командой: он живёт только на")
        print("    GitHub и колёс не публикует, поэтому вынесен из collector.txt:")
        print("      .venv/bin/pip install -r requirements/pymax.txt")
        print("    без него сборщик max падает на старте с RuntimeError.")
    if profile == "b-server1":
        print("  • применить db/migrations 0029–0032 к базе сборщиков;")
        print("  • убедиться, что роль outbox_worker может входить;")
        print("  • проверить, что очередь уходит: "
              "systemctl status m-ranked-target-transfer-sender.")
    print("\n  Порядок и обоснование — в operations/runbooks/DEPLOY.md.")


# --- точка входа ------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Установщик m-ranked")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать действия, ничего не меняя")
    parser.add_argument("--profile", choices=["a", "b-server1", "b-server2"],
                        help="пропустить меню выбора")
    options = parser.parse_args()

    print("\n\033[1mm-ranked — установка\033[0m")
    print(f"релиз: {RELEASE}")
    if options.dry_run:
        print("режим: сухой прогон, изменений не будет")

    profile = options.profile or choose_profile()

    rule("Проверка окружения")
    checks = preflight.for_profile(profile)
    if not show_checks(checks) and not options.dry_run:
        print("\n  Установка невозможна: сначала устраните отмеченные ✗.")
        return 1

    context = Context(profile=profile, release=RELEASE, dry_run=options.dry_run)
    context.answers = questions(profile)

    if not ask_yes("\n  Начать установку?", default=True):
        print("  Отменено.")
        return 1

    handlers = {
        "a": install_profile_a,
        "b-server1": install_profile_b_server1,
        "b-server2": install_profile_b_server2,
    }
    units = handlers[profile](context)

    rule("Проверка юнитов")
    problems = steps.verify_units(context, units)
    if problems:
        for problem in problems:
            print(f"  ! {problem}")
    else:
        print("  ✓ systemd-analyze verify не нашёл замечаний")

    if ask_yes("\n  Включить службы в автозагрузку?", default=True):
        steps.enable_units(context, units, start=ask_yes("  Запустить сейчас?", False))

    next_steps(profile, context)
    rule("Готово")
    print(f"  шагов выполнено: {len(context.log)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Прервано.")
        sys.exit(130)
