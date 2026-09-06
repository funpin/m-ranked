"""Run actual Java/Python receipt producers under separate disposable Linux UIDs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "eclipse-temurin:21-jre"
SOURCES = (
    "backend/src/main/java/org/mranked/admin/infrastructure/IdentityCommandEvidence.java",
    "backend/src/test/java/org/mranked/testing/IdentityReceiptPermissionProbe.java",
    "collector_target/identity_evidence.py",
    "operations/identity_receipts/linux_probe.py",
    "operations/identity_receipts/rehearse.py",
)


def run(output: Path):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    classes = output / "classes"
    classes.mkdir()
    container = "mranked-receipt-it-" + uuid.uuid4().hex[:12]
    commands = []
    report = {"status": "failed", "startedAt": datetime.now(timezone.utc).isoformat(),
              "productionAcceptance": False, "sourceSha256": {
                  name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}}

    def command(name, arguments, timeout=180):
        started = time.monotonic()
        result = subprocess.run(arguments, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout, cwd=ROOT)
        (output / (name + ".log")).write_text(result.stdout)
        commands.append({"name": name, "arguments": arguments, "exitCode": result.returncode,
                         "durationSeconds": round(time.monotonic() - started, 6)})
        if result.returncode:
            raise RuntimeError(f"{name} failed; see its log")
        return result.stdout

    started = time.monotonic()
    created = False
    try:
        javac = str(Path(os.environ["JAVA_HOME"]) / "bin/javac") if os.getenv("JAVA_HOME") else "javac"
        command("compile", [javac, "--release", "21", "-d", str(classes),
                            str(ROOT / SOURCES[0]), str(ROOT / SOURCES[1])])
        report["containerImage"] = json.loads(command("image", ["docker", "image", "inspect", IMAGE]))[0]["Id"]
        command("create", ["docker", "run", "--detach", "--name", container,
                           "--mount", f"type=bind,src={ROOT},dst=/workspace,readonly",
                           "--mount", f"type=bind,src={classes},dst=/classes,readonly",
                           IMAGE, "sleep", "600"])
        created = True
        # Only this disposable container receives development packages. The
        # actual permission rehearsal runs after its network is disconnected.
        command("package-index", ["docker", "exec", container, "apt-get", "update"])
        command("python-install", ["docker", "exec", "--env", "DEBIAN_FRONTEND=noninteractive",
                                   container, "apt-get", "install", "--yes", "--no-install-recommends", "python3"])
        command("disconnect", ["docker", "network", "disconnect", "bridge", container])
        networks = json.loads(command("networks", ["docker", "inspect", "--format",
                              "{{json .NetworkSettings.Networks}}", container]))
        if networks:
            raise RuntimeError("permission probe must have no attached networks")
        result = command("linux-probe", ["docker", "exec", "--env", "PYTHONPATH=/workspace",
                         "--env", "PYTHONDONTWRITEBYTECODE=1", container, "python3",
                         "/workspace/operations/identity_receipts/linux_probe.py"])
        report["linux"] = json.loads(result)
        if report["linux"]["status"] != "pass":
            raise RuntimeError("cross-UID receipt verification failed")
        report["networkDuringProbe"] = "none"
        report["status"] = "pass"
    finally:
        if created:
            command("cleanup", ["docker", "rm", "--force", container])
            report["ownedContainerRemoved"] = True
        report["durationSeconds"] = round(time.monotonic() - started, 6)
        report["commands"] = commands
        encoded = (json.dumps(report, indent=2) + "\n").encode()
        (output / "report.json").write_bytes(encoded)
        (output / "report.json.sha256").write_text(hashlib.sha256(encoded).hexdigest() + "  report.json\n")
    print(json.dumps({key: report[key] for key in ("status", "durationSeconds", "ownedContainerRemoved")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
