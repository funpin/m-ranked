from __future__ import annotations

from dataclasses import dataclass

from .database import Database


@dataclass(frozen=True)
class InstitutionName:
    telegram_username: str
    name: str
    short_name: str


# Canonical display names for the original 24 universities. Full names follow
# the official/M-Rating wording without legal-form prefixes; short names use a
# recognizable university abbreviation or established public brand.
INSTITUTION_NAMES: tuple[InstitutionName, ...] = (
    InstitutionName("mephi_of", "Национальный исследовательский ядерный университет «МИФИ»", "НИЯУ МИФИ"),
    InstitutionName("kbsu1957", "Кабардино-Балкарский государственный университет имени Х.М. Бербекова", "КБГУ"),
    InstitutionName("mslu_official", "Московский государственный лингвистический университет", "МГЛУ"),
    InstitutionName("zgu_university", "Заполярный государственный университет имени Н.М. Федоровского", "ЗГУ"),
    InstitutionName("ksu_kaluga", "Калужский государственный университет имени К.Э. Циолковского", "КГУ им. К.Э. Циолковского"),
    InstitutionName("vvsu_dv", "Владивостокский государственный университет", "ВВГУ"),
    InstitutionName("kchgulife", "Карачаево-Черкесский государственный университет имени У.Д. Алиева", "КЧГУ"),
    InstitutionName("MAIuniversity", "Московский авиационный институт (национальный исследовательский университет)", "МАИ"),
    InstitutionName("nust_misis", "Национальный исследовательский технологический университет «МИСИС»", "НИТУ МИСИС"),
    InstitutionName("miptru", "Московский физико-технический институт (национальный исследовательский университет)", "МФТИ"),
    InstitutionName("marmgu", "Мариупольский государственный университет имени А.И. Куинджи", "МГУ им. А.И. Куинджи"),
    InstitutionName("demidyarsu", "Ярославский государственный университет имени П.Г. Демидова", "ЯрГУ им. П.Г. Демидова"),
    InstitutionName("gubkin_university", "Российский государственный университет нефти и газа (национальный исследовательский университет) имени И.М. Губкина", "Губкинский университет"),
    InstitutionName("bmstu1830", "Московский государственный технический университет имени Н.Э. Баумана (национальный исследовательский университет)", "МГТУ им. Н.Э. Баумана"),
    InstitutionName("ncfulife", "Северо-Кавказский федеральный университет", "СКФУ"),
    InstitutionName("naukamsu", "Московский государственный университет имени М.В. Ломоносова", "МГУ им. М.В. Ломоносова"),
    InstitutionName("stroganovuniversity", "Российский государственный художественно-промышленный университет имени С.Г. Строганова", "РГХПУ им. С.Г. Строганова"),
    InstitutionName("Bru_Live", "Белорусско-Российский университет", "БРУ"),
    InstitutionName("rsukosygin", "Российский государственный университет имени А.Н. Косыгина (Технологии. Дизайн. Искусство)", "РГУ им. А.Н. Косыгина"),
    InstitutionName("unidubna_official", "Государственный университет «Дубна»", "Университет «Дубна»"),
    InstitutionName("rgsu_life", "Российский государственный социальный университет", "РГСУ"),
    InstitutionName("Novosti_AU", "Санкт-Петербургский национальный исследовательский Академический университет имени Ж.И. Алфёрова Российской академии наук", "Академический университет им. Ж.И. Алфёрова"),
    InstitutionName("mpeiuniversity", "Национальный исследовательский университет «МЭИ»", "НИУ «МЭИ»"),
    InstitutionName("mgimo_university", "Московский государственный институт международных отношений (университет) Министерства иностранных дел Российской Федерации", "МГИМО МИД России"),
)


def sync_institution_names(db: Database) -> dict[str, int | list[str]]:
    """Update display names by the already linked official Telegram account."""
    channels = {str(row["username"]).casefold(): row for row in db.list_channels()}
    updated = 0
    missing: list[str] = []
    for item in INSTITUTION_NAMES:
        channel = channels.get(item.telegram_username.casefold())
        if channel is None or channel["institution_id"] is None:
            missing.append(item.telegram_username)
            continue
        if db.update_institution(int(channel["institution_id"]), item.name, item.short_name):
            updated += 1
    return {"updated": updated, "missing": missing}
