from __future__ import annotations

import argparse
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .collector import Collector, normalize_channel_ref
from .config import Settings
from .database import Database
from .max_collector import MaxCollector
from .max_user_api import MaxUserClient
from .institution_names import sync_institution_names
from .m_rating import refresh_m_rating
from .scheduler import run_service
from .public_web import PublicWebCollector
from .rutube_collector import RutubeCollector
from .official_accounts import sync_official_accounts
from .top10_universities import sync_top10_universities
from .telegram_client import TelegramReader
from .vk_collector import VkCollector
from .web.app import create_app


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        return
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(log_path, maxBytes=512 * 1024, backupCount=1)
    file_handler.setFormatter(formatter)
    root.addHandler(console)
    root.addHandler(file_handler)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="python -m app", description="m-ranked")
    sub = command.add_subparsers(dest="command", required=True)
    sub.add_parser("auth", help="Authorize the persistent Telegram user session")
    sub.add_parser("auth-max", help="Authorize the persistent MAX user session")
    sub.add_parser("run", help="Run polling scheduler and web dashboard")
    sub.add_parser("poll-now", help="Run exactly one complete polling cycle")
    sub.add_parser("list-channels", help="List configured channels")
    sub.add_parser("list-institutions", help="List universities and their platform accounts")
    sub.add_parser("sync-official-accounts", help="Import the curated official social accounts")
    sub.add_parser("sync-institution-names", help="Normalize curated university display names")
    sub.add_parser(
        "sync-m-rating-top10",
        help="Import audited universities seen in the recent M-Rating top 10",
    )
    sub.add_parser("refresh-m-rating", help="Refresh all five official M-Rating social slices")
    institution = sub.add_parser("add-institution", help="Create a university container")
    institution.add_argument("name")
    institution.add_argument("--short-name", default=None)
    account = sub.add_parser("add-platform-account", help="Attach a social account to a university")
    account.add_argument("institution_id", type=int)
    account.add_argument("platform", choices=("telegram", "vk", "max", "rutube"))
    account.add_argument("external_key")
    account.add_argument("--username", default=None)
    account.add_argument("--title", default=None)
    account.add_argument("--url", default=None)
    account.add_argument("--access-mode", default="public")
    account.add_argument("--data-quality", default="exact")
    add = sub.add_parser("add-channel", help="Add or re-enable a channel")
    add.add_argument("channel")
    remove = sub.add_parser("remove-channel", help="Disable a channel without deleting history")
    remove.add_argument("channel")
    web = sub.add_parser("web", help="Run dashboard without Telegram (diagnostics)")
    web.add_argument("--host", default=None)
    web.add_argument("--port", type=int, default=None)
    return command


def initialize() -> tuple[Settings, Database]:
    settings = Settings.load()
    settings.ensure_directories()
    setup_logging(settings.log_path)
    db = Database(settings.database_path)
    db.migrate()
    for channel in settings.initial_channels:
        db.add_channel(normalize_channel_ref(channel))
    return settings, db


async def _auth(settings: Settings) -> None:
    api_id, api_hash = settings.require_telegram()
    reader = TelegramReader(api_id, api_hash, settings.telegram_session_path)
    try:
        await reader.authorize_interactive()
    finally:
        await reader.disconnect()


async def _auth_max(settings: Settings) -> None:
    phone = settings.require_max_user()
    client = MaxUserClient(
        phone, settings.max_session_path,
        settings.max_user_first_name, settings.max_user_last_name,
    )
    try:
        await client.authorize_interactive()
    finally:
        await client.close()


async def _poll(settings: Settings, db: Database) -> None:
    auxiliary_collectors = tuple(
        collector for collector in (
            VkCollector(settings, db) if settings.vk_access_token else None,
            MaxCollector(settings, db) if settings.max_user_session_ready else None,
            RutubeCollector(settings, db) if settings.rutube_public_api_enabled else None,
        ) if collector is not None
    )
    if settings.data_source == "public_web":
        collector = PublicWebCollector(settings, db)
        try:
            await collector.poll_cycle()
            for auxiliary in auxiliary_collectors:
                await auxiliary.poll_cycle()
        finally:
            await collector.close()
            for auxiliary in auxiliary_collectors:
                await auxiliary.close()
        return
    api_id, api_hash = settings.require_telegram()
    async with TelegramReader(api_id, api_hash, settings.telegram_session_path) as reader:
        await Collector(settings, db, reader).poll_cycle()
    try:
        for auxiliary in auxiliary_collectors:
            await auxiliary.poll_cycle()
    finally:
        for auxiliary in auxiliary_collectors:
            await auxiliary.close()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings, db = initialize()
    if args.command == "auth":
        asyncio.run(_auth(settings))
    elif args.command == "auth-max":
        asyncio.run(_auth_max(settings))
    elif args.command == "run":
        asyncio.run(run_service(settings, db))
    elif args.command == "poll-now":
        asyncio.run(_poll(settings, db))
    elif args.command == "list-channels":
        for row in db.list_channels():
            state = "enabled" if row["enabled"] else "disabled"
            print(f"@{row['username']}\t{state}\t{row['title'] or ''}")
    elif args.command == "list-institutions":
        accounts_by_institution: dict[int, list[object]] = {}
        for account in db.list_platform_accounts():
            accounts_by_institution.setdefault(int(account["institution_id"]), []).append(account)
        for institution in db.list_institutions():
            print(f"{institution['id']}\t{institution['short_name'] or institution['name']}")
            for account in accounts_by_institution.get(int(institution["id"]), []):
                identity = account["username"] or account["external_key"]
                print(f"  {account['platform']}\t{identity}\t{account['url'] or ''}")
    elif args.command == "sync-official-accounts":
        result = sync_official_accounts(db)
        print(
            f"Synced {result['accounts']} accounts for {result['institutions']} institutions; "
            f"unmatched curated Telegram accounts: {', '.join(result['missing']) or 'none'}; "
            f"institutions without curated social accounts: "
            f"{', '.join(result['uncovered']) or 'none'}"
        )
    elif args.command == "sync-institution-names":
        result = sync_institution_names(db)
        print(
            f"Updated {result['updated']} institution names; "
            f"unmatched Telegram accounts: {', '.join(result['missing']) or 'none'}"
        )
    elif args.command == "sync-m-rating-top10":
        result = sync_top10_universities(db)
        print(
            f"Synced {result['institutions']} institutions and {result['accounts']} accounts; "
            f"created {result['created']} institutions"
        )
    elif args.command == "refresh-m-rating":
        result = asyncio.run(refresh_m_rating(db))
        print(
            f"Updated {result.updated} institutions from {result.period}; "
            f"{result.available} universities available"
        )
    elif args.command == "add-institution":
        institution_id = db.add_institution(args.name, args.short_name)
        print(f"Added institution id={institution_id}")
    elif args.command == "add-platform-account":
        account_id = db.add_platform_account(
            args.institution_id, args.platform, args.external_key,
            args.username, args.title, args.url, args.access_mode, args.data_quality,
        )
        print(f"Added {args.platform} account id={account_id}")
    elif args.command == "add-channel":
        username = normalize_channel_ref(args.channel)
        channel_id = db.add_channel(username)
        print(f"Added @{username} (id={channel_id})")
    elif args.command == "remove-channel":
        username = normalize_channel_ref(args.channel)
        if not db.disable_channel(username):
            parser().error(f"channel @{username} is not configured")
        print(f"Disabled @{username}; existing history was preserved")
    elif args.command == "web":
        import uvicorn
        uvicorn.run(
            create_app(settings, db),
            host=args.host or settings.web_host,
            port=args.port or settings.web_port,
        )
    return 0
