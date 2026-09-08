"""Provision a fresh local Compose database, build real Spring, run the round trip."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
import uuid

from migration.integration.run import Gate, PASSWORDS, ROOT, free_port


def redact_evidence(output: Path, values):
    """Pytest/JUnit may include connection arguments in exception tracebacks."""
    for path in output.rglob("*"):
        if path.is_symlink() or not path.is_file() or path.suffix not in {".log", ".xml", ".json", ".md"}:
            continue
        before = path.read_text(errors="replace")
        after = before
        for value in values:
            after = after.replace(value, "[redacted]")
        if after != before:
            path.write_text(after)


def require_s_final_evidence(reverse: dict, key: str = "sFinal") -> dict:
    """Bind the HTTP admission result to the required independent S-final proofs."""
    final = reverse.get(key, {})
    proofs = [final.get(key, {}) for key in ("identityHistoryVerification", "projectionVerification")]
    revision = proofs[0].get("datasetRevision")
    if (final.get("gate") != "pass" or not isinstance(revision, int) or isinstance(revision, bool)
            or revision <= 0 or not final.get("sourceSha256")
            or any(proof.get("status") != "pass" or proof.get("sourceUnchanged") is not True
                   or proof.get("sourceSha256") != final["sourceSha256"]
                   or proof.get("datasetRevision") != revision for proof in proofs)):
        raise ValueError("required S-final projection and identity-history proofs are missing or inconsistent")
    return final


def require_second_s_final_evidence(reverse: dict) -> dict:
    first=require_s_final_evidence(reverse)
    second=require_s_final_evidence(reverse,"secondSFinal")
    repeat=second.get("repeat",{})
    revision=second["identityHistoryVerification"]["datasetRevision"]
    if (not second.get("batchId") or second["batchId"]==first.get("batchId")
            or second["sourceSha256"]==first["sourceSha256"]
            or repeat.get("gate")!="pass" or repeat.get("rowsWritten")!=0
            or repeat.get("batchId")!=second["batchId"]
            or repeat.get("datasetRevisionBefore")!=revision or repeat.get("datasetRevisionAfter")!=revision):
        raise ValueError("second S-final requires a changed source and exact no-op repeat at one revision")
    return second


def jar_sha256(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("rehearsal JAR must be a regular file")
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("rehearsal JAR changed while reading")
        return digest


def stage_jar(original: Path, destination: Path) -> dict:
    original = original.absolute()
    digest = jar_sha256(original)
    with original.open("rb") as source, destination.open("xb") as target:
        while chunk := source.read(1024 * 1024):
            target.write(chunk)
        target.flush()
        os.fsync(target.fileno())
    destination.chmod(0o400)
    binding = {"originalPath": str(original), "executedPath": str(destination), "sha256": digest}
    verify_jar_binding(binding)
    return binding


def verify_jar_binding(binding: dict):
    if any(jar_sha256(Path(binding[key])) != binding["sha256"] for key in ("originalPath", "executedPath")):
        raise ValueError("rehearsal JAR changed from its recorded SHA-256")


def run(output: Path, *, python: str, maven: str, jar: Path | None = None):
    gate = Gate(output)
    jar_binding = stage_jar(jar, gate.output / "provided-spring.jar") if jar else None
    gate.secrets = {key: secrets.token_hex(24) for key in PASSWORDS}
    project = "mranked-http-it-" + uuid.uuid4().hex[:12]
    pg_port, redis_port = free_port(), free_port()
    db = "http_reverse_it"
    java = str(Path(os.environ["JAVA_HOME"]) / "bin/java") if os.getenv("JAVA_HOME") else "java"
    mvn = [maven, "-Dmranked.build.directory=" + str(gate.output / "backend-build")]
    if os.getenv("MRANKED_MAVEN_REPOSITORY"):
        mvn.append("-Dmaven.repo.local=" + os.environ["MRANKED_MAVEN_REPOSITORY"])
    url = f"jdbc:postgresql://127.0.0.1:{pg_port}/{db}"
    def dsn(role, key):
        return f"host=127.0.0.1 port={pg_port} dbname={db} user={role} password={gate.secrets[key]}"
    with tempfile.TemporaryDirectory(prefix="mranked-http-rehearsal-") as directory:
        envfile = Path(directory) / "services.env"
        envfile.write_text("\n".join(k + "=" + v for k, v in gate.secrets.items()) +
                           f"\nPOSTGRES_PORT={pg_port}\nREDIS_PORT={redis_port}\n")
        envfile.chmod(0o600)
        compose = ["docker", "compose", "--project-name", project, "--env-file", str(envfile),
                   "-f", str(ROOT / "infra/compose.yaml")]
        try:
            gate.command("services", compose + ["up", "-d", "--wait", "postgres"])
            gate.command("create-database", ["docker", "exec", project + "-postgres-1", "psql",
                         "-U", "mranked_bootstrap", "-d", "postgres", "-v", "ON_ERROR_STOP=1",
                         "-c", f"CREATE DATABASE {db} OWNER migration_owner"])
            gate.command("final-schema", mvn + ["-Pschema-integration",
                         "-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase", "test"],
                         env={"MRANKED_REHEARSAL_INSTALL_URL": url,
                              "MRANKED_MIGRATION_TEST_USER": "migration_owner",
                              "MRANKED_MIGRATION_TEST_PASSWORD": gate.secrets["MIGRATION_DB_PASSWORD"]}, cwd=ROOT / "backend")
            if jar_binding is None:
                gate.command("spring-package", mvn + ["-DskipTests", "package"], cwd=ROOT / "backend")
                built = gate.output / "backend-build/m-ranked-backend-0.1.0-SNAPSHOT.jar"
                jar_binding = {"originalPath": str(built), "executedPath": str(built), "sha256": jar_sha256(built)}
            verify_jar_binding(jar_binding)
            report_path = gate.output / "reverse-http.json"
            gate.command("reverse-http", [python, "-m", "pytest", "-q",
                         "tests/test_reverse_sync_postgres.py::test_postgres_reverse_sync_round_trip_preserves_target_identity",
                         "--basetemp=" + str(gate.output / "test-runtime"),
                         "--junitxml=" + str(gate.output / "reverse-http.xml")], env={
                             "MRANKED_TEST_REVERSE_SYNC_POSTGRES_DSN": dsn("migration_bridge", "MIGRATION_BRIDGE_DB_PASSWORD"),
                             "MRANKED_TEST_REVERSE_SYNC_BRIDGE_DSN": dsn("migration_bridge", "MIGRATION_BRIDGE_DB_PASSWORD"),
                             "MRANKED_TEST_REVERSE_SYNC_COLLECTOR_DSN": dsn("collector_ingest", "COLLECTOR_INGEST_DB_PASSWORD"),
                             "MRANKED_TEST_REVERSE_SYNC_ADMIN_DSN": dsn("mranked_bootstrap", "POSTGRES_SUPERUSER_PASSWORD"),
                             "MRANKED_TEST_REVERSE_SYNC_REPORT_PATH": str(report_path),
                             "MRANKED_HTTP_REHEARSAL_JAR": jar_binding["executedPath"],
                             "MRANKED_HTTP_REHEARSAL_JAVA": java,
                             "MRANKED_HTTP_REHEARSAL_API_READ_DSN": dsn("api_read", "API_READ_DB_PASSWORD"),
                             "MRANKED_HTTP_REHEARSAL_API_WRITE_ADMIN_DSN": dsn("api_write_admin", "API_WRITE_ADMIN_DB_PASSWORD"),
                         })
            gate.junit_no_skip(gate.output / "reverse-http.xml")
            verify_jar_binding(jar_binding)
            reverse = json.loads(report_path.read_text())
            report = reverse["cutoverPhases"]["httpUpstreamTransition"]
            assert report["status"] == "pass" and report["requests"] > 0 and report["failures"] == 0
            report["reverseEvidenceSha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
            report["schemaContract"] = reverse["schemaContract"]
            report["reverseSync"] = reverse["reverseSync"]
            report["preservation"] = reverse["preservation"]
            report["sFinal"] = require_s_final_evidence(reverse)
            report["secondSFinal"] = require_second_s_final_evidence(reverse)
            report["accountIdentityTransitions"] = reverse["accountIdentityTransitions"]
            report["release"] = reverse["release"]
            report["springJar"] = dict(jar_binding, provided=jar is not None, originalUnchanged=True, executedUnchanged=True)
            report["checks"] = gate.results
        finally:
            # Only this invocation's UUID Compose project and volumes are removed.
            try:
                gate.command("cleanup", compose + ["down", "--volumes", "--remove-orphans"])
            finally:
                redact_evidence(gate.output, gate.secrets.values())
    report["ownedComposeResourcesRemoved"] = True
    encoded = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    (gate.output / "http-transition.json").write_bytes(encoded)
    (gate.output / "http-transition.json.sha256").write_text(hashlib.sha256(encoded).hexdigest() + "  http-transition.json\n")
    (gate.output / "http-transition.md").write_text(
        "# Isolated HTTP upstream and writer transition\n\n"
        f"Status: **pass**. Actual legacy FastAPI and packaged Spring API; loopback proxy.\n\n"
        f"Route: legacy → target → restarted legacy → target. {report['requests']} real HTTP samples, "
        f"{report['failures']} failed health/read samples; p95 {report['p95ResponseMs']} ms.\n\n"
        "| Transition | Route switch seconds | Verified seconds |\n|---|---:|---:|\n" +
        "".join(f"| {x['from']} → {x['to']} | {x['routeSwitchSeconds']} | {x['verifiedSeconds']} |\n" for x in report["transitions"]) +
        "\nRejected gates, including missing/corrupt original identity receipts, preserved routing and writer ownership. SQLite write locks and database-scoped "
        "PostgreSQL CONNECT grants rejected the inactive collector, verified by real rolled-back writes. "
        "Reverse S0/catch-up/S-final, target collectors, drain/verify/stop and forward identity replay share the same fixture.\n\n"
        "Both S-final admissions include independent projection and complete identity-history proofs bound to their original source SHA-256 and dataset revision. The second follows actual native-ID/name changes, reverse sync and legacy restart; its exact repeat writes zero rows at an unchanged revision.\n\n"
        "Health samples preserve the legacy shape with explicit collector freshness. Target readiness gates admission; reads keep their last published "
        "revision while collectors advance raw data. All disposable Compose resources and application processes were removed.\n\n"
        "Production acceptance remains false: no production load balancer, TLS, cross-host network, or traffic load was exercised.\n"
    )
    print(json.dumps({k: report[k] for k in ("status", "requests", "failures", "durationSeconds", "p95ResponseMs", "ownedComposeResourcesRemoved")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "operations/http_transition/evidence" /
                        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--maven", default=str(ROOT / "backend/mvnw"))
    parser.add_argument("--jar", type=Path, help="Use an unchanged byte-identical private copy of this existing Spring JAR")
    args = parser.parse_args()
    run(args.output, python=args.python, maven=args.maven, jar=args.jar)


if __name__ == "__main__":
    main()
