from __future__ import annotations

import hashlib
import json
from urllib.parse import parse_qs, urlsplit

from operations.storage import agent as agent_module, store
from operations.storage.hub import _clean_report, membership

OBJECT = "11111111-2222-3333-4444-555555555555"


class FakeHub:
    def __init__(self, data: bytes, tasks: list[dict], fail_after: int | None = None):
        self.data, self.tasks, self.reports, self.uploaded = data, tasks, [], b""
        self.requests = 0
        self.fail_after = fail_after
        self.committed = False

    def json(self, method, path, document=None):
        if path == "/node/v1/report":
            self.reports.append(document)
            return 200, {"tasks": self.tasks, "runtime": {"version": "1:server-1:vk", "membership": "server-1:vk",
                                                           "collection": {"trackPostDays": 20}}}
        if path.endswith("/commit"):
            self.committed = hashlib.sha256(self.uploaded).hexdigest() == hashlib.sha256(self.data).hexdigest()
            return 200, {"state": "verified"}
        raise AssertionError(path)

    def request(self, method, path, body=None):
        self.requests += 1
        if self.fail_after is not None and self.requests > self.fail_after:
            return 503, b""
        query = parse_qs(urlsplit(path).query)
        offset = int(query["offset"][0])
        if method == "GET":
            length = int(query["length"][0])
            return 200, self.data[offset:offset + length]
        if offset != len(self.uploaded):
            return 409, json.dumps({"offset": len(self.uploaded)}).encode()
        self.uploaded += body
        return 200, json.dumps({"offset": len(self.uploaded)}).encode()


def task(kind: str, data: bytes, type_: str) -> dict:
    return {"type": type_, "objectId": OBJECT, "kind": kind, "name": "mranked-x.dump", "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def make(tmp_path, hub, monkeypatch, chunk=4):
    monkeypatch.setattr(store, "CHUNK_BYTES", chunk)
    monkeypatch.setattr(agent_module, "unit_states", lambda units: {})
    return agent_module.Agent(hub, tmp_path / "store", tmp_path / "state", [], budget=60)


def test_fetch_resumes_after_a_broken_connection_and_verifies(tmp_path, monkeypatch):
    data = b"0123456789abcdefghij"
    hub = FakeHub(data, [task("backup", data, "fetch")], fail_after=2)
    agent = make(tmp_path, hub, monkeypatch)
    agent.run_once()
    assert json.loads((tmp_path / "state/state.json").read_text())["results"][0]["state"] == "failed"
    assert store.incoming_path(tmp_path / "store", OBJECT).stat().st_size == 8
    hub.fail_after = None
    agent.run_once()
    final = tmp_path / "store/backups/mranked-x.dump"
    assert final.read_bytes() == data
    # Итог прошлого запуска ушёл с отчётом, новый ждёт следующего.
    assert hub.reports[-1]["results"][0]["state"] == "failed"
    saved = json.loads((tmp_path / "state/state.json").read_text())["results"]
    assert saved == [{"objectId": OBJECT, "state": "verified", "sha256": hashlib.sha256(data).hexdigest(),
                      "bytes": len(data)}]
    assert json.loads((tmp_path / "state/runtime.json").read_text())["membership"] == "server-1:vk"


def test_corrupted_download_is_discarded(tmp_path, monkeypatch):
    data = b"payload-bytes"
    bad = dict(task("archive_full", data, "fetch"), sha256="0" * 64)
    hub = FakeHub(data, [bad])
    agent = make(tmp_path, hub, monkeypatch)
    agent.run_once()
    assert not (tmp_path / "store/archive/mranked-x.dump").exists()
    assert not store.incoming_path(tmp_path / "store", OBJECT).exists()


def test_push_uploads_from_where_main_stopped(tmp_path, monkeypatch):
    data = b"backup-file-contents"
    hub = FakeHub(data, [task("backup", data, "push")])
    hub.uploaded = data[:8]
    agent = make(tmp_path, hub, monkeypatch)
    final = tmp_path / "store/backups/mranked-x.dump"
    final.parent.mkdir(parents=True)
    final.write_bytes(data)
    agent.run_once()
    assert hub.uploaded == data and hub.committed


def test_delete_task_removes_the_copy(tmp_path, monkeypatch):
    data = b"old"
    hub = FakeHub(data, [task("backup", data, "delete")])
    agent = make(tmp_path, hub, monkeypatch)
    final = tmp_path / "store/backups/mranked-x.dump"
    final.parent.mkdir(parents=True)
    final.write_bytes(data)
    agent.run_once()
    assert not final.exists()


def test_membership_lists_only_connected_collectors():
    nodes = [{"id": "server-2", "role": "main", "state": "active", "platforms": []},
             {"id": "server-1", "role": "collector", "state": "active", "platforms": ["vk", "telegram"]},
             {"id": "server-3", "role": "collector", "state": "pending", "platforms": ["max"]},
             {"id": "server-4", "role": "collector", "state": "draining", "platforms": ["max"]}]
    # Один подключённый сборщик собирает всё сам: состава нет.
    assert membership(nodes) is None
    nodes[2]["state"] = "active"
    assert membership(nodes) == "server-1:telegram|vk,server-3:max"
    assert membership(nodes[:1]) is None


def test_report_is_sanitised():
    cleaned = _clean_report({"metrics": {"diskFreeBytes": 5, "evil": "x", "load1": True},
                             "units": {"a" * 200: "active"}, "inventory": [{"name": "f", "size": "3"}, "junk"]})
    assert cleaned["metrics"] == {"diskFreeBytes": 5}
    assert list(cleaned["units"]) == ["a" * 80]
    assert cleaned["files"] == [{"name": "f", "size": 3}]
