from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .database import Database


@dataclass(frozen=True)
class Top10University:
    m_rating_code: str
    name: str
    short_name: str
    source_url: str
    telegram_url: str
    vk_url: str
    max_url: str | None = None
    rutube_url: str | None = None

    def accounts(self) -> tuple[tuple[str, str], ...]:
        values = (
            ("telegram", self.telegram_url),
            ("vk", self.vk_url),
            ("max", self.max_url),
            ("rutube", self.rutube_url),
        )
        return tuple((platform, url) for platform, url in values if url)


# Universities absent from the production database that appeared in at least one
# M-Rating top-10 social metric during April-July 2026. Social accounts were
# accepted only when confirmed by a university-owned site or an official account.
TOP10_UNIVERSITIES: tuple[Top10University, ...] = (
    Top10University("94", "Ковровский государственный технологический университет имени В.А. Дегтярева", "КГТУ им. В.А. Дегтярёва", "https://dksta.ru/", "https://t.me/kovrov_kgta", "https://vk.com/kgtu_kovrov", "https://max.ru/id3305007006_biz", "https://rutube.ru/channel/23949910/"),
    Top10University("101", "Курский государственный университет", "КГУ", "https://kursksu.ru/", "https://t.me/Kursksu", "https://vk.com/kursksu", "https://max.ru/kursksu", "https://rutube.ru/channel/25506183/"),
    Top10University("140", "Пермский национальный исследовательский политехнический университет", "ПНИПУ", "https://pstu.ru/", "https://t.me/politehperm", "https://vk.com/politehperm", "https://max.ru/id5902291029_biz", "https://rutube.ru/channel/25507363/"),
    Top10University("62", "Российский университет традиционных художественных промыслов", "РУТХП", "https://vshni.ru/", "https://t.me/vshniacademy", "https://vk.com/vshni_spb", "https://max.ru/id7841003524_biz", "https://rutube.ru/channel/26135429/"),
    Top10University("181", "Сочинский государственный университет", "СГУ", "https://sochi.university/", "https://t.me/sochi_university", "https://vk.com/sochiuniversity", "https://max.ru/id2320051199_biz", "https://rutube.ru/channel/25548246/"),
    Top10University("191", "Тувинский государственный университет", "ТувГУ", "https://tuvsu.ru/", "https://t.me/tuvsu", "https://vk.com/tuvgosuniver", "https://max.ru/id1701010778_biz", "https://rutube.ru/channel/24712763/"),
    Top10University("229", "Ярославский государственный аграрный университет", "Ярославский ГАУ", "https://yaragrovuz.ru/", "https://t.me/yargau", "https://vk.com/yaragrovuz", "https://max.ru/id7602005993_biz", "https://rutube.ru/video/person/59142433/"),
    Top10University("24", "Санкт-Петербургский государственный университет аэрокосмического приборостроения", "ГУАП", "https://guap.ru/piar", "https://t.me/new_guap", "https://vk.com/guap_ru", "https://max.ru/guap_ru", "https://rutube.ru/channel/23832078/"),
    Top10University("175", "Северо-Кавказская государственная академия", "СКГА", "https://ncsa.ru/", "https://t.me/ncsaru", "https://vk.com/ncsa09", "https://max.ru/id0901006061_biz", "https://rutube.ru/channel/24278085/"),
    Top10University("182", "Сыктывкарский государственный университет имени Питирима Сорокина", "СГУ им. Питирима Сорокина", "https://syktsu.ru/", "https://t.me/syktsuofficial", "https://vk.com/syktsu", "https://max.ru/syktsu", "https://rutube.ru/channel/24799153/"),
    Top10University("197", "Уральский государственный архитектурно-художественный университет имени Н.С. Алфёрова", "УрГАХУ", "https://usaaa.ru/", "https://t.me/usaaa_ru", "https://vk.com/uralgaxa", "https://max.ru/uralgaxa"),
    Top10University("198", "Уральский государственный горный университет", "УГГУ", "https://ursmu.ru/", "https://t.me/ursmu_ru", "https://vk.com/ursmu_ru", "https://max.ru/id6661001004_gos", "https://rutube.ru/channel/24609112/"),
    Top10University("206", "Хакасский государственный университет им. Н.Ф. Катанова", "ХГУ им. Н.Ф. Катанова", "https://new.khsu.ru/", "https://t.me/khsu_katanova", "https://vk.com/khsu_ru", "https://max.ru/id1901021449_biz", "https://rutube.ru/channel/24676339/"),
    Top10University("34", "Южно-Уральский государственный университет (национальный исследовательский университет)", "ЮУрГУ", "https://www.susu.ru/", "https://t.me/news_susu", "https://vk.com/susu4you", "https://max.ru/id7453019764_biz", "https://rutube.ru/channel/169610/"),
    Top10University("115", "Российский биотехнологический университет (РОСБИОТЕХ)", "РОСБИОТЕХ", "https://rosbiotech.ru/", "https://t.me/rosbiotech_official", "https://vk.com/rosbiotech_official", "https://max.ru/rosbiotech_official", "https://rutube.ru/u/rosbiotechofficial/"),
    Top10University("215", "Российский государственный университет социальных технологий", "РГУ СоцТех", "https://rgust.ru/", "https://t.me/rgusocteh", "https://vk.com/rgusocteh", "https://max.ru/id7718109215_biz", "https://rutube.ru/channel/25548072/"),
    Top10University("162", "Санкт-Петербургская государственная художественно-промышленная академия имени А.Л. Штиглица", "СПГХПА им. А.Л. Штиглица", "https://ghpa.ru/", "https://t.me/stieglitz_academy", "https://vk.com/stieglitzacademy", "https://max.ru/id7825072672_biz", "https://rutube.ru/channel/24961228/"),
    Top10University("5", "Сибирский государственный университет науки и технологий имени академика М.Ф. Решетнева", "Университет Решетнёва", "https://sibsau.ru/", "https://t.me/reshetnevuniversity", "https://vk.com/sibgu_ru", "https://max.ru/id2462003320_biz", "https://rutube.ru/channel/25502476/"),
    Top10University("76", "Ивановский государственный политехнический университет", "ИВГПУ", "https://ivgpu.ru/", "https://t.me/ivgpu", "https://vk.com/ivgpu", "https://max.ru/id3702698511_biz", "https://rutube.ru/u/ivgpu/"),
    Top10University("11", "Крымский федеральный университет имени В.И. Вернадского", "КФУ им. В.И. Вернадского", "https://cfuv.ru/", "https://t.me/vernadskycfu", "https://vk.com/cfu_official", "https://max.ru/vernadskycfu", "https://rutube.ru/channel/23729603/"),
    Top10University("117", "Московский государственный юридический университет имени О.Е. Кутафина (МГЮА)", "МГЮА", "https://msal.ru/", "https://t.me/msal_kutafina", "https://vk.com/msal_ru", "https://max.ru/msal_ru", "https://rutube.ru/channel/14342986/"),
    Top10University("168", "Санкт-Петербургский государственный университет промышленных технологий и дизайна", "СПбГУПТД", "https://sutd.ru/", "https://t.me/spsutd", "https://vk.com/spsutd", "https://max.ru/spsutd", "https://rutube.ru/channel/23653015/"),
    Top10University("68", "Государственный университет управления", "ГУУ", "https://guu.ru/", "https://t.me/GUUmsk", "https://vk.com/sum_moscow", "https://max.ru/id7721037218_biz", "https://rutube.ru/channel/24203588/"),
    Top10University("96", "Костромской государственный университет", "КГУ", "https://kosgos.ru/", "https://t.me/KGU_Kostroma", "https://vk.com/kostroma_university", "https://max.ru/kostroma_university", "https://rutube.ru/channel/25385759/"),
    Top10University("226", "Приморский государственный аграрно-технологический университет", "Приморский ГАТУ", "https://primacad.ru/", "https://t.me/prim_gsha", "https://vk.com/primgatu", "https://max.ru/id2511010524_biz", "https://rutube.ru/channel/25332477/"),
    Top10University("159", "Рязанский государственный университет имени С.А. Есенина", "РГУ им. С.А. Есенина", "https://rsu-rzn.ru/", "https://t.me/rgu_esenina", "https://vk.com/ryazanuni", "https://max.ru/ryazanuni", "https://rutube.ru/channel/23628768/"),
    Top10University("186", "Тверской государственный университет", "ТвГУ", "https://tversu.ru/", "https://t.me/Tversu", "https://vk.com/tversu", "https://max.ru/id6905000791_gos", "https://rutube.ru/channel/24144175/"),
    Top10University("209", "Чеченский государственный университет имени Ахмата Абдулхамидовича Кадырова", "ЧГУ им. А.А. Кадырова", "https://chesu.ru/", "https://t.me/chesuofficial", "https://vk.com/chesu_ru", "https://max.ru/id2020000570_biz", "https://rutube.ru/channel/25502394/"),
    Top10University("217", "Ярославский государственный технический университет", "ЯГТУ", "https://ystu.ru/", "https://t.me/YaroslavlSTU", "https://vk.com/ystu", "https://max.ru/YaroslavlSTU", "https://rutube.ru/channel/25503199/"),
    Top10University("44", "Байкальский государственный университет", "БГУ", "https://bgu.ru/", "https://t.me/tg_bgu", "https://vk.com/vkbaikalgu", "https://max.ru/id3808011538_gos", "https://rutube.ru/channel/24599393/"),
    Top10University("220", "Верхневолжский государственный агробиотехнологический университет", "Верхневолжский ГАУ", "https://v-gau.ru/", "https://t.me/Agrobioteh37", "https://vk.com/agrobiotex_ivanovo", "https://max.ru/id3728012857_biz", "https://rutube.ru/channel/34092179/"),
    Top10University("212", "Югорский государственный университет", "ЮГУ", "https://ugrasu.ru/", "https://t.me/ugrauniversity", "https://vk.com/ugrasu", "https://max.ru/ugrasu", "https://rutube.ru/channel/23763366/"),
    Top10University("67", "Государственный институт русского языка им. А.С. Пушкина", "Институт Пушкина", "https://pushkin.institute/", "https://t.me/pushkininstitute", "https://vk.com/pushkin_inst", "https://max.ru/pushkin_inst", "https://rutube.ru/channel/28373461/"),
    Top10University("18", "Национальный исследовательский университет ИТМО", "ИТМО", "https://itmo.ru/ru/", "https://t.me/itmoru", "https://vk.com/itmoru", "https://max.ru/itmoru"),
    Top10University("121", "Национальный исследовательский Московский государственный строительный университет", "НИУ МГСУ", "https://mgsu.ru/", "https://t.me/niumgsuofficial", "https://vk.com/mgsu", "https://max.ru/id7716103391_biz", "https://rutube.ru/channel/23789111/"),
    Top10University("106", "МИРЭА — Российский технологический университет", "РТУ МИРЭА", "https://www.mirea.ru/", "https://t.me/rtumirea_official", "https://vk.com/mirea_official", "https://max.ru/rtumirea_official", "https://rutube.ru/u/rtumirea/"),
    Top10University("210", "Чувашский государственный университет имени И.Н. Ульянова", "ЧувГУ", "https://chuvsu.ru/", "https://t.me/chuvsu21", "https://vk.com/chuvsu", "https://max.ru/chuvsu", "https://rutube.ru/u/chuvsu/"),
    Top10University("118", "Московский политехнический университет", "Московский Политех", "https://mospolytech.ru/", "https://t.me/mospolytech", "https://vk.com/moscowpolytech", "https://max.ru/id7719455553_biz", "https://rutube.ru/channel/23764093/"),
    Top10University("211", "Юго-Западный государственный университет", "ЮЗГУ", "https://swsu.ru/", "https://t.me/swsu_kursk", "https://vk.com/swsu_kursk", "https://max.ru/swsu_kursk", "https://rutube.ru/channel/25367241/"),
    Top10University("240", "Донецкий национальный технический университет", "ДонНТУ", "https://доннту.рф/", "https://t.me/donetsk_donntu", "https://vk.com/donetsk.donntu", "https://max.ru/id9303013012_biz", "https://rutube.ru/u/donntu/"),
    Top10University("77", "Ивановский государственный университет", "ИвГУ", "https://ivanovo.ac.ru/", "https://t.me/IvSUonTheRun", "https://vk.com/ivsu_37", None, "https://rutube.ru/channel/23698283/"),
    Top10University("170", "Саратовская государственная юридическая академия", "СГЮА", "https://ssla.ru/", "https://t.me/ssla_official", "https://vk.com/ssla_official", "https://max.ru/ssla_official", "https://rutube.ru/u/ssla/"),
)


def _external_key(platform: str, url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if not parts:
        raise ValueError(f"Account URL has no identity: {url}")
    key = parts[-1].lstrip("@")
    return key.casefold() if platform == "telegram" else key


def sync_top10_universities(db: Database) -> dict[str, int]:
    """Create the audited universities and enable every confirmed account."""
    institutions_by_name = {
        str(row["name"]).strip().casefold(): int(row["id"])
        for row in db.list_institutions()
    }
    created = 0
    synced_accounts = 0
    for university in TOP10_UNIVERSITIES:
        normalized_name = university.name.strip().casefold()
        institution_id = institutions_by_name.get(normalized_name)
        if institution_id is None:
            institution_id = db.add_institution(university.name, university.short_name)
            institutions_by_name[normalized_name] = institution_id
            created += 1

        telegram_username = _external_key("telegram", university.telegram_url)
        db.add_channel(telegram_username, institution_id=institution_id)
        for platform, url in university.accounts():
            key = _external_key(platform, url)
            db.add_platform_account(
                institution_id,
                platform,
                key,
                username=key,
                url=url,
                access_mode="user_session" if platform == "max" else "public",
                data_quality="exact",
            )
            synced_accounts += 1

    return {
        "institutions": len(TOP10_UNIVERSITIES),
        "created": created,
        "accounts": synced_accounts,
    }
