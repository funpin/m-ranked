"""Курсор истории несёт id снимка внутри UUID.

У синтетических и перенесённых точек id снимка отрицательный (64 бита со
знаком): прежнее `uuid.UUID(int=id)` падало на них, и история с такой точкой
на границе страницы отвечала 500.
"""
import pytest

from api.routes.query import snapshot_cursor, snapshot_from_cursor


@pytest.mark.parametrize("snapshot_id", [1, 7946054, (1 << 63) - 1, -1, -5314622057626384356, -(1 << 63)])
def test_snapshot_cursor_round_trips_signed_64_bit_ids(snapshot_id):
    assert snapshot_from_cursor(snapshot_cursor(snapshot_id)) == snapshot_id


def test_positive_ids_keep_the_old_cursor_text():
    # Курсоры, выданные до правки, остаются действительными.
    assert snapshot_cursor(7946054) == "00000000-0000-0000-0000-000000793f46"


@pytest.mark.parametrize("text", ["00000000-0000-0000-0000-000000000000", "00000000-0000-0001-0000-000000000000"])
def test_cursor_outside_signed_64_bits_is_rejected(text):
    assert snapshot_from_cursor(text) is None
