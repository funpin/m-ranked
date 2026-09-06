"""Provision a disposable real Nginx to verify the rollback mutation fence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]


def run(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    container = "mranked-nginx-it-" + uuid.uuid4().hex[:12]
    commands = []
    def command(name, args):
        started = time.monotonic()
        value = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        (output/(name+".log")).write_text(value.stdout)
        commands.append({"name": name, "arguments": args, "exitCode": value.returncode,
                         "durationSeconds": round(time.monotonic()-started, 6)})
        if value.returncode: raise RuntimeError(name + " failed; see log")
        return value.stdout
    created = False
    report = {"status": "failed", "productionAcceptance": False}
    try:
        command("create", ["docker", "run", "--detach", "--name", container,
                           "--cap-add", "SYS_PTRACE",
                           "--mount", f"type=bind,src={ROOT},dst=/workspace,readonly",
                           "eclipse-temurin:21-jre", "sleep", "600"])
        created = True
        command("packages", ["docker", "exec", container, "apt-get", "update"])
        command("install", ["docker", "exec", "--env", "DEBIAN_FRONTEND=noninteractive", container,
                            "apt-get", "install", "--yes", "--no-install-recommends", "python3", "nginx"])
        command("disconnect", ["docker", "network", "disconnect", "bridge", container])
        assert json.loads(command("networks", ["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", container])) == {}
        report = json.loads(command("probe", ["docker", "exec", container, "python3", "/workspace/operations/http_transition/nginx_probe.py"]))
        assert report["status"] == "pass"
        report["networkDuringProbe"] = "none"
        report["privateContainerAddedCapabilities"] = ["SYS_PTRACE"]
        report["hostPidNamespaceShared"] = False
    finally:
        if created:
            for filename in ("receipt-nginx-error.log", "receipt-nginx-access.log"):
                result = subprocess.run(["docker", "exec", container, "cat", "/tmp/"+filename],
                                        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5)
                (output/filename).write_text(result.stdout)
            command("cleanup", ["docker", "rm", "--force", container])
            report["ownedContainerRemoved"] = True
        report["commands"] = commands
        report["harnessSha256"] = {str(file.relative_to(ROOT)): hashlib.sha256(file.read_bytes()).hexdigest()
                                   for file in (Path(__file__), Path(__file__).with_name("nginx_probe.py"))}
        encoded = (json.dumps(report, indent=2)+"\n").encode()
        (output/"report.json").write_bytes(encoded)
        (output/"report.json.sha256").write_text(hashlib.sha256(encoded).hexdigest()+"  report.json\n")
    print(json.dumps({key: report[key] for key in ("status", "continuousReads", "readFailures", "ownedContainerRemoved")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    run(parser.parse_args().output)
