"""Run the real pinned HTTPS client inside a network-denied disposable container."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

from migration.integration.run import Gate, ROOT

IMAGE = "eclipse-temurin@sha256:7a65df4b22d2de92d4e04056e884f3b9122d70b21e2847fd66084278bd0ce037"


def run(output: Path, maven: str):
    gate=Gate(output)
    mvn=[maven,"-Dmranked.build.directory="+str(gate.output/"backend-build")]
    if os.getenv("MRANKED_MAVEN_REPOSITORY"):
        mvn.append("-Dmaven.repo.local="+os.environ["MRANKED_MAVEN_REPOSITORY"])
    gate.command("network-tests",mvn+["-Dtest=PinnedHttpsClientNetworkTest,TelegramEmojiHttpGatewayTest,CustomEmojiServiceTest","test"],cwd=ROOT/"backend")
    junit=gate.output/"backend-build/surefire-reports/TEST-org.mranked.operations.infrastructure.PinnedHttpsClientNetworkTest.xml"
    gate.junit_no_skip(junit)
    document=ET.parse(junit).getroot()
    classpath=next(p.attrib["value"] for p in document.findall("./properties/property") if p.attrib["name"]=="java.class.path")
    library=gate.output/"lib";library.mkdir()
    for item in classpath.split(os.pathsep):
        path=Path(item)
        if path.suffix==".jar":
            target=library/path.name
            if target.exists() and target.read_bytes()!=path.read_bytes():
                raise ValueError("classpath jar collision")
            shutil.copyfile(path,target)
    name="mranked-egress-it-"+uuid.uuid4().hex[:12]
    # The JARs/classes are immutable inside this process. Only report and /tmp are writable.
    evidence=gate.output/"network-evidence";evidence.mkdir(mode=0o700)
    uid,gid=os.getuid(),os.getgid()
    if uid==0:
        uid,gid=65532,65532
        os.chown(evidence,uid,gid)
    command=["docker","run","--name",name,"--pull","never","--network","none","--read-only",
             "--cap-drop","ALL","--security-opt","no-new-privileges","--pids-limit","128",
             "--memory","384m","--cpus","2","--user",f"{uid}:{gid}",
             "--tmpfs","/tmp:rw,nosuid,nodev,size=64m","--mount",f"type=bind,source={gate.output},target=/rehearsal,readonly",
             "--mount",f"type=bind,source={evidence},target=/evidence",IMAGE,"java","-Xmx128m",
             "-cp","/rehearsal/backend-build/classes:/rehearsal/backend-build/test-classes:/rehearsal/lib/*",
             "org.mranked.operations.infrastructure.HttpsNetworkRehearsal","/evidence","--require-egress-denied"]
    try:
        gate.command("isolated-egress",command,timeout=180)
    finally:
        # A timed-out CLI must not leave an owned container running.
        found=subprocess.run(["docker","ps","-aq","--filter","name=^"+name+"$"],capture_output=True,text=True,check=True).stdout.strip()
        if found:
            gate.command("cleanup",["docker","rm","--force",name])
    report=json.loads((evidence/"https-network.json").read_text())
    assert report["status"]=="pass" and report["externalEgressPolicyExercised"] is True
    report.update(containerImage=IMAGE,containerRemoved=True,containerUser=uid,capabilities=[],readOnlyRoot=True,
                  heapLimitBytes=128*1024*1024,containerMemoryBytes=384*1024*1024,commands=gate.results)
    encoded=(json.dumps(report,indent=2)+"\n").encode()
    (gate.output/"https-egress.json").write_bytes(encoded)
    (gate.output/"https-egress.json.sha256").write_text(hashlib.sha256(encoded).hexdigest()+"  https-egress.json\n")
    (gate.output/"https-egress.md").write_text(
        "# Local DNS/TLS and kernel egress rehearsal\n\nStatus: **pass**. "
        f"{len(report['cases'])} cases, {report['durationSeconds']:.3f} seconds inside the isolated container.\n\n"
        "The actual shared HTTPS client resolved DNS over loopback UDP and connected to a real local TLS server. "
        "The tests covered hostname validation, manual redirects, mixed DNS answers, rebinding, private IP rejection, "
        "body/header limits and total deadline cancellation. The container had only loopback, no capabilities, "
        "a read-only root, a non-root user, bounded heap/memory, and no route for a TEST-NET egress attempt.\n\n"
        "Only the test constructor permits exactly 127.0.0.1 for a positive local TLS fixture. The production address "
        "policy was separately exercised and rejected that DNS result before HTTP. No runtime flag disables this policy.\n\n"
        "Production acceptance remains false. Live Telegram/CDN responses and the approved production egress proxy/firewall "
        "deployment remain external gates. The rehearsal does not change production network configuration.\n")
    print(json.dumps({"status":"pass","cases":len(report["cases"]),"containerRemoved":True}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"operations/https_egress/evidence"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--maven",default=str(ROOT/"backend/mvnw"))
    args=parser.parse_args();run(args.output,args.maven)


if __name__=="__main__":main()
