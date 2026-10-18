#!/usr/bin/env python3
"""Собрать /etc/m-ranked/nginx/geo-home.conf из DB-IP «IP to Country Lite».

Россия и СНГ (HOME) — «свои» страны для лимита по странам в traffic.conf;
остальные посетители с куки проверки делят свой общий лимит холодных страниц.
Вход — dbip-country-lite-ГГГГ-ММ.csv.gz (download.db-ip.com, CC BY 4.0,
обновляется 1-го числа). Диапазоны «начало,конец,страна» сворачиваются в CIDR:
модуль geo nginx принимает диапазоны только для IPv4.

    build-geo-home.py dbip-country-lite-2026-10.csv.gz /etc/m-ranked/nginx/geo-home.conf

Файл пишется атомарно; слишком короткий результат — ошибка (битая или чужая
база не должна сделать «чужими» всех).
"""
from __future__ import annotations

import argparse
import gzip
import ipaddress
import os
import sys
from pathlib import Path

# ZZ — служебные и частные адреса (запросы с самого сервера).
HOME = ("RU", "BY", "KZ", "UZ", "KG", "TJ", "TM", "AM", "AZ", "MD", "GE", "ZZ")
MIN_NETWORKS = 1000


def networks(lines, home=HOME):
    for line in lines:
        parts = line.strip().split(",")
        if len(parts) != 3 or parts[2] not in home:
            continue
        first, last = ipaddress.ip_address(parts[0]), ipaddress.ip_address(parts[1])
        yield from ipaddress.summarize_address_range(first, last)


def render(found, source: str) -> str:
    lines = [f"# Собрано build-geo-home.py из {source} (DB-IP, CC BY 4.0): Россия, СНГ, служебные.",
             "# Источник адреса — X-MRanked-Client от публичного слоя: шлюз видит только 127.0.0.1.",
             "geo $http_x_mranked_client $m_ranked_home_country {",
             "    default 0;"]
    lines += [f"    {network} 1;" for network in found]
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with gzip.open(args.database, "rt", encoding="ascii") as stream:
        nets = list(networks(stream))
    # collapse_addresses не смешивает версии: IPv4 и IPv6 — по отдельности.
    found = [*ipaddress.collapse_addresses(n for n in nets if n.version == 4),
             *ipaddress.collapse_addresses(n for n in nets if n.version == 6)]
    if len(found) < MIN_NETWORKS:
        print(f"слишком мало сетей ({len(found)}): база не та или битая", file=sys.stderr)
        return 1
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(render(found, args.database.name), encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, args.output)
    print(f"{args.output}: {len(found)} сетей")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
