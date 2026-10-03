from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from operations.storage.reconcile import Node, StoredObject, plan, validate_storage_policy

NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)
GB = 1024 ** 3
MAIN = Node("server-2", "main", "active", True, 13 * GB, 3 * GB)
S1 = Node("server-1", "collector", "active", True, 19 * GB, 3 * GB)
S3 = Node("server-3", "storage", "active", True, 50 * GB, 3 * GB)
POLICY = {"backupCopies": 1, "backupNodes": ["server-2", "server-1"], "archiveNodes": ["server-2", "server-1"]}


def backup(name: str, age_days: int, size: int = 3 * GB) -> StoredObject:
    return StoredObject(name, "backup", size, NOW - timedelta(days=age_days))


def test_new_backup_is_copied_to_every_policy_server():
    result = plan([MAIN, S1], [backup("b1", 0)], {("b1", "server-2"): "verified"}, POLICY)
    assert result.want == [("b1", "server-1")] and not result.delete


def test_older_backup_retires_only_after_the_newest_is_verified_somewhere():
    objects = [backup("new", 0), backup("old", 1)]
    pending = plan([MAIN, S1], objects, {("old", "server-2"): "verified", ("old", "server-1"): "verified",
                                         ("new", "server-2"): "transferring"}, POLICY)
    assert pending.retire == [] and not pending.delete
    ready = plan([MAIN, S1], objects, {("old", "server-2"): "verified", ("old", "server-1"): "verified",
                                       ("new", "server-2"): "verified"}, POLICY)
    assert ready.retire == ["old"]
    assert sorted(ready.delete) == [("old", "server-1"), ("old", "server-2")]


def test_moving_archives_off_main_keeps_the_copy_until_targets_are_verified():
    policy = {**POLICY, "archiveNodes": ["server-1", "server-3"]}
    archive = StoredObject("a", "archive_full", 2 * GB, NOW)
    first = plan([MAIN, S1, S3], [archive], {("a", "server-2"): "verified"}, policy)
    assert sorted(first.want) == [("a", "server-1"), ("a", "server-3")] and not first.delete
    middle = plan([MAIN, S1, S3], [archive], {("a", "server-2"): "verified", ("a", "server-1"): "verified",
                                              ("a", "server-3"): "transferring"}, policy)
    assert not middle.delete
    done = plan([MAIN, S1, S3], [archive], {("a", "server-2"): "verified", ("a", "server-1"): "verified",
                                            ("a", "server-3"): "verified"}, policy)
    assert done.delete == [("a", "server-2")]


def test_browse_file_always_stays_on_main():
    policy = {**POLICY, "archiveNodes": ["server-1", "server-3"]}
    browse = StoredObject("v", "archive_browse", GB, NOW)
    result = plan([MAIN, S1, S3], [browse], {("v", "server-2"): "verified", ("v", "server-1"): "verified",
                                             ("v", "server-3"): "verified"}, policy)
    assert result.delete == [] and result.want == []


def test_copy_between_remote_servers_is_relayed_through_main():
    policy = {**POLICY, "backupNodes": ["server-3"]}
    result = plan([MAIN, S1, S3], [backup("b", 0)], {("b", "server-1"): "verified"}, policy)
    assert sorted(result.want) == [("b", "server-2"), ("b", "server-3")]


def test_server_without_room_waits_and_is_reported():
    tight = Node("server-1", "collector", "active", True, 4 * GB, 3 * GB)
    result = plan([MAIN, tight], [backup("b", 0)], {("b", "server-2"): "verified"}, POLICY)
    assert result.want == [] and result.blocked == [("b", "server-1", "no_space")]


def test_disabled_or_draining_servers_receive_nothing_and_unreachable_copies_are_kept():
    disabled = Node("server-1", "collector", "disabled", True, 19 * GB, 3 * GB)
    result = plan([MAIN, disabled], [backup("b", 0)], {("b", "server-2"): "verified",
                                                      ("b", "server-1"): "verified"}, POLICY)
    assert result.want == [] and result.delete == []


def test_policy_validation():
    good = validate_storage_policy({"coldAfterDays": 30, "backupCopies": 2, "backupNodes": ["server-2"],
                                    "archiveNodes": ["server-2", "server-1"]}, ["server-1", "server-2"])
    assert good["archiveNodes"] == ["server-2", "server-1"]
    for bad in ({"coldAfterDays": 10}, {"archiveNodes": ["server-2"]}, {"backupNodes": ["server-9"]}):
        with pytest.raises(ValueError):
            validate_storage_policy({"coldAfterDays": 30, "backupCopies": 1, "backupNodes": ["server-2"],
                                     "archiveNodes": ["server-2", "server-1"], **bad}, ["server-1", "server-2"])
