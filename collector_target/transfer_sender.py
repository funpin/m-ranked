"""Автономная отправка запечатанных пачек потребителю.

В профиле B эта служба — единственный путь доставки. Сборщик только
запечатывает пачку в outbox в той же транзакции, что и запись, а сеть сюда не
пускает: прежде он отправлял конверт сам, сразу после каждой записи и прямо
под общим замком записи. Сетевой вызов на Сервер 2 с новым TLS-рукопожатием
держал замок, и остальные три сборщика ждали его по 5–14 секунд на каждый
аккаунт — циклы перерастали свои слоты, и в ряду замеров появлялись провалы.

Служба опрашивает очередь по расписанию и доводит её до нуля. Доставка
идемпотентна — потребитель различает дубликаты по ``batch_id``, — поэтому
повтор после сбоя безопасен.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .repository import PostgresCollectorRepository
from .transfer import HttpsMtlsTransport, InProcessTransport, PostgresDataAdapter
from .transfer import PostgresTransferProducer, _row


logger = logging.getLogger("transfer_sender")

DEFAULT_INTERVAL_SECONDS = 15
DEFAULT_BATCH_LIMIT = 50
# Подтверждённый конверт хранит свою полезную нагрузку и после доставки. Окно
# нужно не ради места, а ради замены: если потребитель потеряет данные, отдать
# их заново можно только пока конверт цел. Потерять Сервер 2 может не больше,
# чем набралось с его последнего ежесуточного снимка, поэтому окно — сутки и
# два часа запаса. Очередь растёт на 1.3 ГиБ в сутки, и прежние 48 часов
# держали на тесном диске сборщика 2.7 ГиБ, из которых половина не защищала
# уже ничего.
DEFAULT_RETENTION_HOURS = 26
DEFAULT_PURGE_LIMIT = 2000


def _positive_int(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} должен быть целым числом") from error
    if not low <= value <= high:
        raise ValueError(f"{name} должен быть в пределах [{low}, {high}]")
    return value


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} обязателен")
    return value


def build_transport(repository: PostgresCollectorRepository) -> Any:
    """Транспорт по режиму переноса, объявленному для сборщиков."""
    mode = os.environ.get("COLLECTOR_TRANSFER_MODE", "https-mtls").strip().lower()
    if mode == "in-process":
        return InProcessTransport(PostgresDataAdapter(repository))
    if mode != "https-mtls":
        raise ValueError(
            "COLLECTOR_TRANSFER_MODE должен быть in-process или https-mtls"
        )
    return HttpsMtlsTransport(
        _required("COLLECTOR_TRANSFER_HTTPS_ENDPOINT"),
        certificate=_required("COLLECTOR_TRANSFER_CLIENT_CERTIFICATE"),
        private_key=_required("COLLECTOR_TRANSFER_PRIVATE_KEY"),
        ca_bundle=_required("COLLECTOR_TRANSFER_CA_BUNDLE"),
    )


def publish_metrics(path: Path, delivered: int, backlog: int, failures: int) -> None:
    """Текстовый файл для node_exporter. Пишется атомарно, как и везде."""
    body = (
        "# HELP mranked_transfer_sender_delivered_total Доставленные конверты\n"
        "# TYPE mranked_transfer_sender_delivered_total counter\n"
        f"mranked_transfer_sender_delivered_total {delivered}\n"
        "# HELP mranked_transfer_sender_backlog Конверты, ожидающие отправки\n"
        "# TYPE mranked_transfer_sender_backlog gauge\n"
        f"mranked_transfer_sender_backlog {backlog}\n"
        "# HELP mranked_transfer_sender_failures_total Неудачные проходы\n"
        "# TYPE mranked_transfer_sender_failures_total counter\n"
        f"mranked_transfer_sender_failures_total {failures}\n"
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(body, encoding="utf-8")
    temporary.replace(path)


def backlog_size(repository: PostgresCollectorRepository) -> int:
    """Сколько конвертов ещё ждут отправки.

    Строка читается через тот же помощник, что и везде в модуле переноса:
    соединение репозитория отдаёт её отображением, а не кортежем, и обращение
    по индексу здесь ломается.
    """
    with repository._connection() as connection:
        row = connection.execute(
            """SELECT count(*) AS backlog FROM ops_and_admin.transfer_outbox
                WHERE state IN ('sealed','sent')"""
        ).fetchone()
    return 0 if row is None else int(_row(row, "backlog", 0))


def run() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    interval = _positive_int(
        "COLLECTOR_TRANSFER_SENDER_INTERVAL_SECONDS",
        DEFAULT_INTERVAL_SECONDS, 1, 3600,
    )
    limit = _positive_int(
        "COLLECTOR_TRANSFER_SENDER_BATCH_LIMIT", DEFAULT_BATCH_LIMIT, 1, 500,
    )
    producer_id = _required("COLLECTOR_TRANSFER_PRODUCER_ID")
    retention_hours = _positive_int(
        "COLLECTOR_TRANSFER_SENDER_RETENTION_HOURS",
        DEFAULT_RETENTION_HOURS, 0, 24 * 90,
    )
    purge_limit = _positive_int(
        "COLLECTOR_TRANSFER_SENDER_PURGE_LIMIT", DEFAULT_PURGE_LIMIT, 1, 50000,
    )
    metrics_file = os.environ.get("COLLECTOR_TRANSFER_SENDER_METRICS_FILE", "").strip()
    metrics_path = Path(metrics_file) if metrics_file else None

    repository = PostgresCollectorRepository(_required("COLLECTOR_DATABASE_URL"))
    repository.transfer_producer_id = producer_id
    producer = PostgresTransferProducer(repository, build_transport(repository))

    stop = threading.Event()
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, lambda *_: stop.set())

    delivered_total = 0
    purged_total = 0
    failures_total = 0
    logger.info(
        "transfer sender started producer=%s interval=%ss limit=%s",
        producer_id, interval, limit,
    )
    while not stop.is_set():
        try:
            # Один проход доводит очередь до нуля, а не отдаёт один конверт:
            # ради этого служба и существует.
            while not stop.is_set():
                sent = producer.deliver_pending(limit=limit)
                if sent == 0:
                    break
                delivered_total += sent
                logger.info("delivered=%s total=%s", sent, delivered_total)
            # Очистка идёт после доставки и только по подтверждённым записям:
            # неподтверждённое не удаляется никогда и ни при каком пороге.
            if retention_hours:
                horizon = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
                removed = producer.purge_acknowledged(
                    before=horizon, limit=purge_limit,
                )
                if removed:
                    purged_total += removed
                    logger.info("purged=%s total=%s", removed, purged_total)
        except Exception as error:  # noqa: BLE001 — журнал важнее падения
            failures_total += 1
            logger.warning("delivery pass failed: %s", type(error).__name__)
        if metrics_path is not None:
            try:
                publish_metrics(
                    metrics_path, delivered_total,
                    backlog_size(repository), failures_total,
                )
            except Exception:  # noqa: BLE001 — метрики не должны ронять отправку
                logger.debug("metrics publication failed", exc_info=True)
        stop.wait(interval)
    close = getattr(producer.transport, "close", None)
    if callable(close):
        close()
    repository.close()
    logger.info(
        "transfer sender stopped delivered=%s purged=%s",
        delivered_total, purged_total,
    )
    return 0


if __name__ == "__main__":
    sys.exit(run())
