"""Real loopback HTTP apps and database fences; never a deployment controller.

The caller supplies one empty, disposable Flyway database and owns its lifecycle.
The reverse-sync integration test drives the same data through every transition.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
from uuid import uuid4
import socket
import sqlite3
import subprocess
import threading
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

PLATFORMS = ("telegram", "vk", "max", "rutube")


def local_database(dsn: str) -> dict[str, str]:
    values = conninfo_to_dict(dsn)
    if (values.get("host") not in {"127.0.0.1", "localhost"}
            or not re.fullmatch(r"[a-z0-9_]+_it", values.get("dbname", ""))):
        raise ValueError("HTTP rehearsal requires an explicit loopback *_it database")
    return values


def fetch(url: str) -> tuple[int, bytes, dict[str, str]]:
    try:
        response = urlopen(url, timeout=5)
    except HTTPError as response:
        return response.code, response.read(4 * 1024 * 1024 + 1), {key.lower(): value for key, value in response.headers.items()}
    with response:
        body = response.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024:
            raise ValueError("bounded rehearsal response exceeded")
        return response.status, body, {key.lower(): value for key, value in response.headers.items()}


def port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_http(url: str, *, process=None) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process and process.poll() is not None:
            raise RuntimeError("owned Spring process exited; inspect private application log")
        try:
            if fetch(url)[0] == 200:
                return
        except (OSError, TimeoutError):
            pass
        time.sleep(.1)
    raise RuntimeError("owned HTTP server startup deadline exceeded")


class LegacyServer:
    def __init__(self, database: Path, work: Path):
        import uvicorn
        from app.config import Settings
        from app.database import Database
        from migration.legacy_reference import create_app
        from dataclasses import replace
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        settings = Settings(None, None, work / "telegram.session", database, (), 60,
                            336, 90, 15, 2., "127.0.0.1", 8080, "Europe/Moscow",
                            work / "legacy.log", 200, 20)
        settings = replace(settings, max_session_path=work / "max.session")
        self.server = uvicorn.Server(uvicorn.Config(create_app(settings, Database(database)),
                                    host="127.0.0.1", log_level="error", access_log=False))
        self.thread = threading.Thread(target=self.server.run,
                                       kwargs={"sockets": [self.socket]}, daemon=True)
        self.thread.start()
        wait_http(self.url + "/health")

    def close(self):
        self.server.should_exit = True
        self.thread.join(10)
        self.socket.close()
        if self.thread.is_alive():
            raise RuntimeError("owned legacy server failed to stop")


class TransitionVerifier:
    def __init__(self, work: Path, live: Path, admin_dsn: str, collector_dsn: str):
        self.work = work
        self.work.mkdir(mode=0o700)
        self.admin_dsn, self.collector_dsn = admin_dsn, collector_dsn
        admin, collector = local_database(admin_dsn), local_database(collector_dsn)
        api = local_database(os.environ["MRANKED_HTTP_REHEARSAL_API_READ_DSN"])
        self.write_admin_dsn = os.environ["MRANKED_HTTP_REHEARSAL_API_WRITE_ADMIN_DSN"]
        write_admin = local_database(self.write_admin_dsn)
        assert all((x["host"], x.get("port", "5432"), x["dbname"]) ==
                   (admin["host"], admin.get("port", "5432"), admin["dbname"])
                   for x in (collector, api, write_admin)), "all roles must target the same disposable database"
        assert collector["user"] == "collector_ingest" and api["user"] == "api_read"
        assert write_admin["user"] == "api_write_admin"
        self.database = admin["dbname"]
        self.live = live
        self.fences: list[sqlite3.Connection] = []
        self.legacy = None
        self.java = None
        self.java_log = None
        self.proxy = None
        self.proxy_thread = None
        self.sampler = None
        self.stop_sampling = threading.Event()
        self.route_lock = threading.Lock()
        self.route = "legacy"
        self.phase = 0
        self.phase_names = ["initial-legacy"]
        self.observations: list[dict] = []
        self.transitions: list[dict] = []
        self.rejected_gates: list[dict] = []
        self.writer_checks: list[dict] = []
        self.admin_commands: list[dict] = []
        self.started = time.monotonic()
        self.finished = False
        self.acl_changed = False
        self.owned_read_role = None
        self.jar = Path(os.environ["MRANKED_HTTP_REHEARSAL_JAR"]).resolve(strict=True)
        try:
            # Only this disposable database ACL changes; never ALTER ROLE or shared settings.
            with psycopg.connect(admin_dsn, autocommit=True) as connection:
                attrs = connection.execute("SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname='collector_ingest'").fetchone()
                assert attrs == (False, False, False)
                assert connection.execute("SELECT count(*) FROM ingest.collection_run").fetchone()[0] == 0
                # PUBLIC is a pseudo-role: inspect ACL directly, including the default ACL.
                self.old_connect_grantees = {row[0] for row in connection.execute("SELECT CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END FROM pg_database d CROSS JOIN LATERAL aclexplode(coalesce(d.datacl,acldefault('d',d.datdba))) a WHERE d.datname=current_database() AND a.privilege_type='CONNECT'").fetchall()}
                # api_write_admin inherits api_read. A direct CONNECT revoke on
                # the admin role alone cannot fence it. Give a fresh read-only
                # login this database's CONNECT, inheriting exactly api_read's
                # table/function rights; do not alter any existing role.
                read_role = "http_reader_"+uuid4().hex
                read_password = secrets.token_hex(24)
                connection.execute(sql.SQL("CREATE ROLE {} LOGIN INHERIT PASSWORD {} IN ROLE api_read").format(
                    sql.Identifier(read_role),sql.Literal(read_password)))
                self.owned_read_role = read_role
                self.acl_changed = True
                connection.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC, api_read, collector_ingest, api_write_admin").format(sql.Identifier(self.database)))
                connection.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, migration_bridge, migration_owner, maintenance").format(sql.Identifier(self.database),sql.Identifier(self.owned_read_role)))
                api = dict(api,user=self.owned_read_role,password=read_password)
                self.acl_changed = True
            self.legacy = LegacyServer(live, work)
            api_port, management_port = port(), port()
            self.api_url = f"http://127.0.0.1:{api_port}"
            from migration.integration.fixture_auth import bcrypt_hash
            java = os.environ.get("MRANKED_HTTP_REHEARSAL_JAVA", "java")
            self.fixture_password = secrets.token_hex(24)
            password_hash = bcrypt_hash(self.fixture_password, java=java,
                repository=Path(os.environ.get("MRANKED_MAVEN_REPOSITORY", str(Path.home()/".m2/repository"))))
            env = dict(os.environ) | {
                "SPRING_DATASOURCE_URL": f"jdbc:postgresql://{api['host']}:{api.get('port', '5432')}/{api['dbname']}",
                "SPRING_DATASOURCE_USERNAME": api["user"], "SPRING_DATASOURCE_PASSWORD": api["password"],
                "SPRING_FLYWAY_ENABLED": "false", "MRANKED_ADMIN_DATABASE_ENABLED": "true",
                "MRANKED_ADMIN_DATABASE_URL": f"jdbc:postgresql://{api['host']}:{api.get('port', '5432')}/{api['dbname']}",
                "MRANKED_ADMIN_DATABASE_USERNAME": "api_write_admin",
                "MRANKED_ADMIN_DATABASE_PASSWORD": write_admin["password"],
                "SPRING_APPLICATION_JSON": json.dumps({"mranked.admin.auth.users": [
                    {"username": "http-fixture-admin", "password-hash": password_hash, "roles": ["ADMIN"]}]}),
                "MRANKED_CACHE_REDIS_ENABLED": "false", "SERVER_ADDRESS": "127.0.0.1",
                "SERVER_PORT": str(api_port), "MANAGEMENT_SERVER_ADDRESS": "127.0.0.1",
                "MANAGEMENT_SERVER_PORT": str(management_port),
                "MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE": "health,prometheus",
                "MRANKED_EXPORTS_SPOOL_DIRECTORY": str(work / "exports"),
                "MRANKED_HEALTH_DATA_SOURCE": "mtproto",
                "MRANKED_INTEGRATIONS_TELEGRAM": "missing", "MRANKED_INTEGRATIONS_VK": "missing",
                "MRANKED_INTEGRATIONS_MAX": "missing", "MRANKED_INTEGRATIONS_RUTUBE": "configured",
            }
            # Do not inherit test/bootstrap credentials into the read-only API process.
            for key in tuple(env):
                if ((key.startswith("MRANKED_TEST_") or key.startswith("MRANKED_HTTP_REHEARSAL_")
                     or "PASSWORD" in key) and key not in {"SPRING_DATASOURCE_PASSWORD", "MRANKED_ADMIN_DATABASE_PASSWORD"}):
                    env.pop(key)
            self.java_log = (work / "spring.log").open("w")
            self.java = subprocess.Popen([os.environ.get("MRANKED_HTTP_REHEARSAL_JAVA", "java"),
                                          "-jar", str(self.jar)], env=env,
                                         stdout=self.java_log, stderr=subprocess.STDOUT)
            wait_http(self.api_url + "/api/v1/health/live", process=self.java)
            assert fetch(self.api_url + "/api/v1/health/ready")[0] == 503
            self.writer_check("initial-legacy", "legacy")
            self._start_proxy()
            self.sampler = threading.Thread(target=self._sample, daemon=True)
            self.sampler.start()
            self.await_phase_samples()
            self.reject_bad_gate("target", {"status": "pass", "critical_mismatches": 0},
                                 reason="unready actual Spring API on empty database")
        except BaseException:
            self.close()
            raise

    def _start_proxy(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                platform = parse_qs(parsed.query).get("platform", ["vk"])[0]
                if parsed.path not in {"/health", "/read"} or platform not in PLATFORMS:
                    self.send_error(404)
                    return
                with owner.route_lock:
                    route, phase = owner.route, owner.phase
                    base = owner.legacy.url if route == "legacy" else owner.api_url
                path = ("/health" if route == "legacy" else "/api/v1/health/legacy") if parsed.path == "/health" else (
                    f"/?platform={platform}" if route == "legacy" else f"/api/v1/overview?platform={platform}")
                try:
                    status, body, headers = fetch(base + path)
                    self.send_response(status)
                    self.send_header("Content-Type", headers.get("content-type", "application/octet-stream"))
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("X-Rehearsal-Upstream", route)
                    self.send_header("X-Rehearsal-Phase", str(phase))
                    self.end_headers()
                    self.wfile.write(body)
                except (OSError, TimeoutError):
                    self.send_error(502)
        self.proxy = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.proxy.daemon_threads = True
        self.proxy_url = f"http://127.0.0.1:{self.proxy.server_port}"
        self.proxy_thread = threading.Thread(target=self.proxy.serve_forever,
                                             kwargs={"poll_interval": .05}, daemon=True)
        self.proxy_thread.start()

    def _sample(self):
        while not self.stop_sampling.is_set():
            for path in ("/health", *(f"/read?platform={p}" for p in PLATFORMS)):
                start = time.monotonic()
                observation = {"atSeconds": round(start - self.started, 6), "path": path}
                try:
                    status, body, headers = fetch(self.proxy_url + path)
                    route = headers.get("x-rehearsal-upstream")
                    valid = status == 200 and bool(body)
                    if path.startswith("/read"):
                        if route == "target":
                            payload = json.loads(body)
                            valid = valid and bool(payload.get("items"))
                            observation["datasetRevision"] = payload.get("datasetRevision")
                        else:
                            valid = valid and b"<html" in body.lower()
                    observation.update(status=status, upstream=route,
                                       phase=int(headers.get("x-rehearsal-phase", "-1")), valid=valid,
                                       bodySha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
                except Exception as error:
                    observation.update(status=0, valid=False, errorType=type(error).__name__, phase=self.phase)
                observation["durationMs"] = round((time.monotonic() - start) * 1000, 3)
                self.observations.append(observation)
                if len(self.observations) > 30000:
                    self.stop_sampling.set()
                    return
            self.stop_sampling.wait(.1)

    def await_phase_samples(self):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            samples = [item for item in self.observations if item.get("phase") == self.phase]
            if any(not item["valid"] for item in samples):
                raise AssertionError("actual HTTP read/health failure; see transition evidence")
            if len({item["path"] for item in samples}) == 5 and len(samples) >= 10:
                return
            time.sleep(.05)
        raise AssertionError("continuous sampler did not cover all four platforms and health")

    def _collector_access(self, enabled: bool):
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            command = "GRANT CONNECT ON DATABASE {} TO collector_ingest, api_write_admin" if enabled else "REVOKE CONNECT ON DATABASE {} FROM collector_ingest, api_write_admin"
            connection.execute(sql.SQL(command).format(sql.Identifier(self.database)))
            if not enabled:
                # Revoke FIRST so new sessions cannot race the drain check. Existing sessions
                # survive REVOKE; the old SQLite writer stays fenced if any remain.
                assert connection.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND usename IN ('collector_ingest','api_write_admin')").fetchone()[0] == 0, "collector still has a live session"

    def _freeze_legacy(self):
        connection = sqlite3.connect(self.live, timeout=.5)
        connection.execute("BEGIN IMMEDIATE")
        self.fences.append(connection)

    def writer_check(self, stage: str, expected: str):
        legacy_allowed = False
        try:
            with sqlite3.connect(self.live, timeout=.05) as connection:
                connection.execute("BEGIN IMMEDIATE")
                assert connection.execute("UPDATE institutions SET name=name WHERE id=1").rowcount == 1
                connection.rollback()
                legacy_allowed = True
        except sqlite3.OperationalError as error:
            if "locked" not in str(error):
                raise
        collector_allowed = False
        try:
            with psycopg.connect(self.collector_dsn, connect_timeout=2) as connection:
                connection.execute("INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id) VALUES(gen_random_uuid(),'vk','http-writer-probe','rehearsal',now(),'succeeded',gen_random_uuid())")
                connection.rollback()
                collector_allowed = True
        except psycopg.Error as error:
            # libpq's startup FATAL can lose SQLSTATE; do not mistake arbitrary
            # connectivity/authentication failures for a successful writer fence.
            startup_connect_denied = (error.sqlstate is None
                                     and "permission denied for database" in str(error)
                                     and "does not have CONNECT privilege" in str(error))
            if error.sqlstate != "42501" and not startup_connect_denied:
                raise
            with psycopg.connect(self.admin_dsn) as admin:
                assert admin.execute("SELECT has_database_privilege('collector_ingest',current_database(),'CONNECT')").fetchone()[0] is False
        admin_allowed = False
        try:
            with psycopg.connect(self.write_admin_dsn, connect_timeout=2) as connection:
                connection.execute("SELECT ops_and_admin.catalog_command('account.native_id',%s,0,%s::jsonb,'http-writer-probe',%s)",
                    (uuid4(), '{"nativeId":""}', uuid4()))
                connection.rollback()
                admin_allowed = True
        except psycopg.Error as error:
            startup_denied = error.sqlstate is None and "permission denied for database" in str(error) and "does not have CONNECT privilege" in str(error)
            if error.sqlstate != "42501" and not startup_denied: raise
            with psycopg.connect(self.admin_dsn) as admin:
                assert admin.execute("SELECT has_database_privilege('api_write_admin',current_database(),'CONNECT')").fetchone()[0] is False
        assert admin_allowed == (expected == "target")
        assert (legacy_allowed, collector_allowed) == (expected == "legacy", expected == "target")
        row = {"stage": stage, "legacySqliteWriteAllowed": legacy_allowed,
               "postgresCollectorWriteAllowed": collector_allowed, "postgresAdminWriteAllowed": admin_allowed, "owner": expected,
               "probe": "actual UPDATE / INSERT followed by ROLLBACK; closed writer rejected by database"}
        self.writer_checks.append(row)
        return row

    def admin_identity_command(self, account_id, *, native_id=None, presentation=False) -> dict:
        """Use the real authenticated Spring command path and its durable input producer."""
        import httpx
        assert self.route == "target"
        with psycopg.connect(self.admin_dsn) as connection:
            institution, version, canonical = connection.execute(
                "SELECT institution_id,row_version,canonical_external_id FROM catalog.platform_account WHERE id=%s",
                (account_id,)).fetchone()
        path = "/api/v1/admin/catalog/accounts"
        body = ({"institutionId": str(institution), "expectedRowVersion": version, "platform": "max",
                 "reference": canonical, "title": "Бета MAX — Java admin", "url": "https://max.ru/"+canonical}
                if presentation else {"expectedRowVersion": version, "nativeId": native_id})
        if not presentation: path += "/"+str(account_id)+"/native-id"
        correlation = str(uuid4())
        with httpx.Client(base_url=self.api_url, auth=("http-fixture-admin",self.fixture_password), timeout=60) as client:
            session = client.get("/api/v1/admin/catalog/session")
            assert session.status_code == 200
            csrf = session.json()
            response = client.post(path,json=body,headers={csrf["headerName"]:csrf["token"], "X-Correlation-Id":correlation})
            assert response.status_code == 200, (response.status_code,response.text)
            result = response.json()
            assert result["outcome"] == "succeeded" and result["targetId"] == str(account_id)
            repeated = client.post(path,json=body,headers={csrf["headerName"]:csrf["token"], "X-Correlation-Id":correlation})
            assert repeated.status_code == 200 and repeated.json() == result
        self.admin_commands.append({"path":path,"correlationId":correlation,"datasetRevision":result["datasetRevision"],
                                    "targetId":result["targetId"],"sameCommandReplayUnchanged":True})
        return result

    def _validate_gate(self, destination: str, gate: dict):
        if gate.get("status") != "pass" or gate.get("critical_mismatches") != 0:
            raise ValueError("reconciliation gate is not green")
        if destination == "target" and fetch(self.api_url + "/api/v1/health/ready")[0] != 200:
            raise ValueError("actual target readiness is not green")

    def reject_bad_gate(self, destination: str, gate: dict, *, reason: str):
        before = self.route, self.phase, len(self.fences)
        try:
            assert destination == "target"
            # Exercise the very same transition entry point as a successful admission.
            self._admit_target(gate)
        except ValueError:
            assert before == (self.route, self.phase, len(self.fences))
            self.writer_check("rejected-gate", self.route)
            self.rejected_gates.append({"reason": reason, "routingUnchanged": True,
                                        "writersUnchanged": True, "phase": self.phase})
            return
        raise AssertionError("non-green transition was accepted")

    def to_target(self, gate: dict):
        self.reject_bad_gate("target", {"status": "fail", "critical_mismatches": 1},
                             reason="injected critical reconciliation mismatch")
        self._admit_target(gate)

    def verify_legacy_health_contract(self):
        legacy_status, legacy_body, _ = fetch(self.legacy.url + "/health")
        target_status, target_body, headers = fetch(self.api_url + "/api/v1/health/legacy")
        assert legacy_status == target_status == 200
        legacy, target = json.loads(legacy_body), json.loads(target_body)
        assert legacy == target, {"legacy": legacy, "target": target}
        assert headers.get("cache-control") == "no-store"
        self.health_compatibility = {"status": "pass", "fieldsEqual": True,
                                     "canonicalJsonSha256": hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()}

    def _admit_target(self, gate: dict):
        started = time.monotonic()
        self._validate_gate("target", gate)
        assert self.route == "legacy"
        self._freeze_legacy()
        self.writer_check("all-writers-frozen", "none")
        self._collector_access(True)
        writers = self.writer_check("target-authoritative", "target")
        self._switch("target", started, writers)

    def to_legacy(self, gate: dict, synchronized_database: Path):
        started = time.monotonic()
        self._validate_gate("legacy", gate)
        assert self.route == "target"
        self._collector_access(False)
        self.writer_check("all-writers-frozen-before-rollback", "none")
        # Drain/verify/stop already completed. Launch a real new legacy app on that exact file.
        new_legacy = LegacyServer(synchronized_database, self.work)
        old_legacy = self.legacy
        with self.route_lock:
            self.legacy = new_legacy
        self.live = synchronized_database
        writers = self.writer_check("legacy-authoritative-after-reverse-sync", "legacy")
        self._switch("legacy", started, writers)
        old_legacy.close()

    def _switch(self, destination, started, writers):
        with self.route_lock:
            previous = self.route
            self.route = destination
            self.phase += 1
            self.phase_names.append(destination)
        route_at = time.monotonic()
        self.await_phase_samples()
        self.transitions.append({"from": previous, "to": destination, "phase": self.phase,
                                 "routeSwitchSeconds": round(route_at - started, 6),
                                 "verifiedSeconds": round(time.monotonic() - started, 6),
                                 "writers": writers})

    def finish(self) -> dict:
        self.await_phase_samples()
        self.stop_sampling.set()
        self.sampler.join(10)
        assert self.phase_names == ["initial-legacy", "target", "legacy", "target"]
        assert self.observations and all(x["valid"] for x in self.observations)
        assert len(self.rejected_gates) == 7
        assert len(self.admin_commands) == 4
        latency = sorted(item["durationMs"] for item in self.observations)
        per_phase = dict(Counter(str(item["phase"]) for item in self.observations))
        report = {"reportVersion": 1, "status": "pass", "environment": "disposable-local",
                  "generatedAt": datetime.now(timezone.utc).isoformat(),
                  "productionAcceptance": False, "productionRouteSwitch": False,
                  "database": self.database, "springJarSha256": hashlib.sha256(self.jar.read_bytes()).hexdigest(),
                  "routeSequence": self.phase_names, "transitions": self.transitions,
                  "rejectedGates": self.rejected_gates, "writerChecks": self.writer_checks,
                  "actualJavaAdminCommands": self.admin_commands,
                  "healthSemantics": "continuous legacy-compatible health; collector freshness is explicit, target readiness additionally gates admission; reads retain last published revision during collector lag",
                  "healthCompatibility": self.health_compatibility,
                  "requests": len(self.observations), "failures": 0, "samplesPerPhase": per_phase,
                  "durationSeconds": round(time.monotonic() - self.started, 6),
                  "p95ResponseMs": latency[int(.95 * (len(latency) - 1))], "maxResponseMs": latency[-1],
                  "observations": self.observations,
                  "limitations": ["loopback transport and local database locks; no production load balancer, TLS or cross-host network exercised",
                                   "authoritative collectors fenced; reverse sync writes its separate shadow SQLite as part of rollback protocol"]}
        self.finished = True
        return report

    def close(self):
        self.stop_sampling.set()
        if self.sampler:
            self.sampler.join(10)
        if self.proxy:
            self.proxy.shutdown()
            self.proxy.server_close()
        if self.legacy:
            self.legacy.close()
            self.legacy = None
        if self.java:
            self.java.terminate()
            try:
                self.java.wait(10)
            except subprocess.TimeoutExpired:
                self.java.kill()
                self.java.wait(10)
            self.java = None
        if self.java_log:
            self.java_log.close()
        for connection in self.fences:
            connection.rollback()
            connection.close()
        self.fences.clear()
        if self.acl_changed:
            with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
                for role in ("PUBLIC", "collector_ingest", "api_write_admin", "api_read", "migration_bridge", "migration_owner", "maintenance"):
                    enabled = role in self.old_connect_grantees
                    command = "GRANT CONNECT ON DATABASE {} TO {}" if enabled else "REVOKE CONNECT ON DATABASE {} FROM {}"
                    connection.execute(sql.SQL(command).format(sql.Identifier(self.database),
                                       sql.SQL("PUBLIC") if role == "PUBLIC" else sql.Identifier(role)))
            self.acl_changed = False
        if self.owned_read_role:
            with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
                connection.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(sql.Identifier(self.database),sql.Identifier(self.owned_read_role)))
                connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(self.owned_read_role)))
            self.owned_read_role = None
        if not self.finished and self.observations:
            (self.work / "http-failure.json").write_text(json.dumps({"status": "fail", "observations": self.observations}, indent=2) + "\n")
