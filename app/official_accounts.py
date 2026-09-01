from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .database import Database


@dataclass(frozen=True)
class OfficialAccount:
    platform: str
    url: str
    source_url: str


# Only accounts confirmed by a university-owned website or its official Telegram
# channel are included here. Missing platforms are deliberately left absent.
OFFICIAL_ACCOUNTS: dict[str, tuple[OfficialAccount, ...]] = {
    "Bru_Live": (
        OfficialAccount("rutube", "https://rutube.ru/channel/25369590/", "https://t.me/Bru_Live"),
    ),
    "vvsu_dv": (
        OfficialAccount("vk", "https://vk.com/vvsu_dv", "https://t.me/vvsu_dv"),
        OfficialAccount("max", "https://max.ru/vvsu_dv", "https://t.me/vvsu_dv"),
        OfficialAccount("rutube", "https://rutube.ru/channel/25579450/", "https://t.me/vvsu_dv"),
    ),
    "unidubna_official": (
        OfficialAccount("vk", "https://vk.com/unidubna_official", "https://t.me/unidubna_official"),
        OfficialAccount("max", "https://max.ru/unidubna_official", "https://t.me/unidubna_official"),
    ),
    "zgu_university": (
        OfficialAccount("rutube", "https://rutube.ru/video/person/32480368/", "https://t.me/zgu_university"),
    ),
    "kbsu1957": (
        OfficialAccount("vk", "https://vk.com/kbsu.official", "https://t.me/kbsu1957"),
        OfficialAccount("max", "https://max.ru/id0711037537_biz", "https://t.me/kbsu1957"),
        OfficialAccount("rutube", "https://rutube.ru/u/kbsu/", "https://t.me/kbsu1957"),
    ),
    "ksu_kaluga": (
        OfficialAccount("vk", "https://vk.com/kgu_kaluga", "https://t.me/ksu_kaluga"),
        OfficialAccount("rutube", "https://rutube.ru/channel/26820487/", "https://t.me/ksu_kaluga"),
    ),
    "kchgulife": (
        OfficialAccount("vk", "https://vk.com/kchgu", "https://kchgu.ru/"),
        OfficialAccount("rutube", "https://rutube.ru/u/kchgu/", "https://ok.kchgu.ru/"),
    ),
    "bmstu1830": (
        OfficialAccount("vk", "https://vk.com/bmstu1830", "https://t.me/bmstu1830"),
        OfficialAccount("rutube", "https://rutube.ru/channel/24869232/", "https://t.me/bmstu1830"),
    ),
    "miptru": (
        OfficialAccount("vk", "https://vk.com/miptru", "https://t.me/miptru"),
        OfficialAccount("rutube", "https://rutube.ru/channel/23787794/", "https://t.me/miptru"),
    ),
    "naukamsu": (
        OfficialAccount("vk", "https://vk.com/msu_official", "https://t.me/naukamsu"),
        OfficialAccount("max", "https://max.ru/msu_official", "https://t.me/naukamsu"),
        OfficialAccount("rutube", "https://rutube.ru/channel/23642102/", "https://t.me/naukamsu"),
    ),
    "marmgu": (
        OfficialAccount("vk", "https://vk.com/mgumariupolkuindzhi", "https://t.me/marmgu"),
        OfficialAccount("max", "https://max.ru/id9310004516_biz", "https://t.me/marmgu"),
        OfficialAccount("rutube", "https://rutube.ru/channel/30508329/", "https://t.me/marmgu"),
    ),
    "MAIuniversity": (
        OfficialAccount("vk", "https://vk.com/maiuniversity", "https://t.me/MAIuniversity"),
        OfficialAccount("max", "https://max.ru/maiuniversity", "https://t.me/MAIuniversity"),
        OfficialAccount("rutube", "https://rutube.ru/u/maiuniversity/", "https://t.me/MAIuniversity"),
    ),
    "mgimo_university": (
        OfficialAccount("vk", "https://vk.com/mgimo", "https://t.me/mgimo_university"),
        OfficialAccount("max", "https://max.ru/mgimo_university", "https://t.me/mgimo_university"),
        OfficialAccount("rutube", "https://rutube.ru/u/mgimo/", "https://t.me/mgimo_university"),
    ),
    "mslu_official": (
        OfficialAccount("vk", "https://vk.com/mslu_official", "https://linguanet.ru/sotsialnye-seti.php"),
        OfficialAccount("max", "https://max.ru/mslu_official", "https://linguanet.ru/sotsialnye-seti.php"),
    ),
    "mephi_of": (
        OfficialAccount("max", "https://max.ru/mephi_official", "https://t.me/mephi_of"),
        OfficialAccount("rutube", "https://rutube.ru/channel/24152419/", "https://t.me/mephi_of"),
    ),
    "nust_misis": (
        OfficialAccount("vk", "https://vk.com/nust_misis", "https://t.me/nust_misis"),
        OfficialAccount("max", "https://max.ru/nust_misis", "https://t.me/nust_misis"),
        OfficialAccount("rutube", "https://rutube.ru/channel/23750838/", "https://t.me/nust_misis"),
    ),
    "mpeiuniversity": (
        OfficialAccount("vk", "https://vk.com/mpei_ru", "https://t.me/mpeiuniversity"),
        OfficialAccount("max", "https://max.ru/mpeiuniversity", "https://t.me/mpeiuniversity"),
        OfficialAccount("rutube", "https://rutube.ru/channel/23770848/", "https://t.me/mpeiuniversity"),
    ),
    "rsukosygin": (
        OfficialAccount("vk", "https://vk.com/rsukosygin", "https://t.me/rsukosygin"),
        OfficialAccount("max", "https://max.ru/id7705001020_biz", "https://t.me/rsukosygin"),
        OfficialAccount("rutube", "https://rutube.ru/u/rguk/", "https://t.me/rsukosygin"),
    ),
    "gubkin_university": (
        OfficialAccount("vk", "https://vk.com/club71938736", "https://t.me/gubkin_university"),
        OfficialAccount("max", "https://max.ru/gubkin_university", "https://t.me/gubkin_university"),
    ),
    "rgsu_life": (
        OfficialAccount("vk", "https://vk.com/rgsu_official", "https://t.me/rgsu_life"),
        OfficialAccount("max", "https://max.ru/rgsu_official", "https://t.me/rgsu_life"),
    ),
    "stroganovuniversity": (
        OfficialAccount("vk", "https://vk.com/rghpu_stroganova", "https://t.me/stroganovuniversity"),
    ),
    "Novosti_AU": (
        OfficialAccount("vk", "https://vk.com/alferov_university", "https://t.me/Novosti_AU"),
    ),
    "ncfulife": (
        OfficialAccount("vk", "https://vk.com/ncfu_main", "https://t.me/ncfulife"),
        OfficialAccount("max", "https://max.ru/ncfu_main", "https://t.me/ncfulife"),
        OfficialAccount("rutube", "https://rutube.ru/channel/23921803/", "https://t.me/ncfulife"),
    ),
    "demidyarsu": (
        OfficialAccount("vk", "https://vk.com/demidyarsu", "https://t.me/demidyarsu"),
        OfficialAccount("max", "https://max.ru/demidyarsu", "https://t.me/demidyarsu"),
        OfficialAccount("rutube", "https://rutube.ru/u/demidyarsu/", "https://t.me/demidyarsu"),
    ),
}


def external_key(account: OfficialAccount) -> str:
    path = [part for part in urlparse(account.url).path.split("/") if part]
    if not path:
        raise ValueError(f"Account URL has no identity: {account.url}")
    return path[-1].lstrip("@")


def sync_official_accounts(db: Database) -> dict[str, int | list[str]]:
    """Attach curated official accounts to institutions matched by Telegram account."""
    channels = {str(row["username"]).casefold(): row for row in db.list_channels()}
    added = 0
    institutions: set[int] = set()
    missing: list[str] = []
    for telegram_username, accounts in OFFICIAL_ACCOUNTS.items():
        channel = channels.get(telegram_username.casefold())
        if channel is None or channel["institution_id"] is None:
            missing.append(telegram_username)
            continue
        institution_id = int(channel["institution_id"])
        institutions.add(institution_id)
        for account in accounts:
            db.add_platform_account(
                institution_id,
                account.platform,
                external_key(account),
                username=external_key(account),
                url=account.url,
                access_mode=(
                    "public" if account.platform == "vk"
                    else "user_session" if account.platform == "max"
                    else "public"
                ),
                data_quality=(
                    "exact" if account.platform in {"vk", "max"} else "unavailable"
                ),
            )
            added += 1
    curated_usernames = {username.casefold() for username in OFFICIAL_ACCOUNTS}
    uncovered = sorted(
        str(row["username"])
        for key, row in channels.items()
        if row["institution_id"] is not None and key not in curated_usernames
    )
    return {
        "accounts": added,
        "institutions": len(institutions),
        "missing": missing,
        "uncovered": uncovered,
    }
