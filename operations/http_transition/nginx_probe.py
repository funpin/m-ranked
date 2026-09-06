"""Exercise the unchanged route fragments in real disposable Linux Nginx."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

ROOT = Path("/workspace")
CONFIG = Path("/etc/m-ranked/nginx")
CONFIG.mkdir(parents=True, exist_ok=True)
READS = ["/health", "/", "/overview/telegram?page=2", "/institutions/1", "/posts/1",
         "/platform-accounts/1", "/platform-posts/1", "/manage", "/export/posts.csv"]
LOCK = threading.Lock()
UPSTREAM = []
SAMPLES = []
STOP = threading.Event()
HOLD_STARTED = threading.Event()
HOLD_RELEASE = threading.Event()


class LegacyTransport(BaseHTTPRequestHandler):
    """Only identifies transport ownership; application semantics are tested separately."""
    def answer(self):
        if self.path == "/manage/hold":
            HOLD_STARTED.set()
            assert HOLD_RELEASE.wait(timeout=5)
        with LOCK:
            UPSTREAM.append({"method": self.command, "path": self.path})
        body = json.dumps({"upstream": "legacy", "method": self.command, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)
    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = answer
    def log_message(self, *_): pass


def request(path, method="GET"):
    started = time.monotonic()
    try:
        response = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:18080" + path, method=method), timeout=2)
    except urllib.error.HTTPError as response_error:
        response = response_error
    with response:
        response.read()
        return {"path": path, "method": method, "status": response.status,
                "phase": response.headers.get("X-Rehearsal-Phase"),
                "milliseconds": round((time.monotonic() - started) * 1000, 3)}


def sample():
    while not STOP.is_set():
        for path in ("/health", "/", "/manage"):
            try: SAMPLES.append(request(path))
            except Exception as failure: SAMPLES.append({"status": 0, "error": type(failure).__name__})
        STOP.wait(0.01)


def switch(phase, filename, *, start=False):
    source = ROOT / "operations/nginx/routes" / filename
    temporary = CONFIG / "routes-next.conf"
    shutil.copyfile(source, temporary)
    temporary.replace(CONFIG / "routes-active.conf")
    Path("/tmp/receipt-nginx.conf").write_text(f'''
worker_processes 1;
pid /tmp/receipt-nginx.pid;
error_log /tmp/receipt-nginx-error.log notice;
events {{ worker_connections 128; }}
http {{
  access_log /tmp/receipt-nginx-access.log;
  upstream m_ranked_legacy {{ server 127.0.0.1:8090; }}
  server {{
    listen 127.0.0.1:18080;
    add_header X-Rehearsal-Phase "{phase}" always;
    include /etc/m-ranked/nginx/routes-active.conf;
  }}
}}
''')
    subprocess.run(["nginx", "-t", "-c", "/tmp/receipt-nginx.conf"], check=True, capture_output=True)
    if phase == "rollback-freeze":
        command = ["bash", "-euc", '''
source /workspace/operations/scripts/nginx-freeze-barrier.sh
systemctl() { cat /tmp/receipt-nginx.pid; }
mranked_nginx_freeze_capture /usr/sbin/nginx
/usr/sbin/nginx -c /tmp/receipt-nginx.conf -s reload
mranked_nginx_freeze_wait /usr/sbin/nginx 5
printf 'verified-old-workers=%s\\n' "${#MRANKED_NGINX_OLD_WORKERS[@]}"
''']
    else:
        command = ["nginx", "-c", "/tmp/receipt-nginx.conf"] + ([] if start else ["-s", "reload"])
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        raise AssertionError({"command": command[0], "exitCode": result.returncode, "stderr": result.stderr})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if request("/health")["phase"] == phase: return
        except (OSError, urllib.error.URLError): pass
        time.sleep(0.01)
    raise AssertionError("Nginx did not activate expected route")


def run():
    started = time.monotonic()
    server = ThreadingHTTPServer(("127.0.0.1", 8090), LegacyTransport)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    shutil.copyfile(ROOT / "operations/nginx/proxy-common.conf", CONFIG / "proxy-common.conf")
    thread = threading.Thread(target=sample, daemon=True)
    accepted, rejected, transitions, barrier_checks = [], [], [], []
    persistent = None
    try:
        switch("legacy-before", "phase-0-legacy.conf", start=True)
        assert request("/manage/accounts", "POST")["status"] == 200
        thread.start()
        for phase, file in (("legacy-before", "phase-0-legacy.conf"),
                            ("rollback-freeze", "phase-4-rollback-freeze.conf"),
                            ("legacy-after", "phase-0-legacy.conf")):
            mark = time.monotonic()
            held, held_thread = [], None
            if phase == "rollback-freeze":
                persistent = http.client.HTTPConnection("127.0.0.1", 18080, timeout=2)
                persistent.request("GET", "/health")
                existing = persistent.getresponse()
                assert existing.status == 200
                existing.read()
                assert persistent.sock is not None
                held_thread = threading.Thread(target=lambda: held.append(request("/manage/hold", "POST")))
                held_thread.start()
                assert HOLD_STARTED.wait(timeout=2)
                threading.Timer(0.6, HOLD_RELEASE.set).start()
                mark = time.monotonic()
            if phase != "legacy-before": switch(phase, file)
            activation = round(time.monotonic() - mark, 6)
            transitions.append({"phase": phase, "activationSeconds": activation})
            if phase == "rollback-freeze":
                held_thread.join(timeout=3)
                assert activation >= 0.5 and len(held) == 1 and held[0]["status"] == 200
                assert held[0]["phase"] == "legacy-before"
                try:
                    persistent.request("POST", "/manage/accounts")
                    stale = persistent.getresponse()
                    stale.read()
                    assert stale.status == 403, "old keepalive accepted a mutation after barrier"
                    keepalive = "denied403"
                except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError):
                    keepalive = "oldConnectionClosed"
                finally:
                    persistent.close()
                barrier_checks.append({"heldPriorMutationCompletedBeforeAdmission": True,
                                       "oldKeepaliveAfterBarrier": keepalive,
                                       "waitedSeconds": activation})
            for path in READS:
                for method in ("GET", "HEAD"):
                    result = request(path, method)
                    generations = {phase, "rollback-freeze"} if phase == "legacy-after" else {phase}
                    assert result["status"] == 200 and result["phase"] in generations, result
                    accepted.append(result)
            if phase == "rollback-freeze":
                for path in ("/manage", "/manage/accounts", "/manage/accounts/native-id", "/manage/mrating/import", "/", "/health"):
                    for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
                        with LOCK: before = len([x for x in UPSTREAM if x["method"] not in ("GET", "HEAD")])
                        result = request(path, method)
                        with LOCK: after = len([x for x in UPSTREAM if x["method"] not in ("GET", "HEAD")])
                        assert result["status"] == 403 and before == after, result
                        rejected.append(result)
                for path in ("/api/v1/admin", "/api/v1/admin/", "/api/v1/admin/catalog/accounts", "/%61pi/v1/admin/catalog/accounts"):
                    for method in ("GET", "HEAD", "POST", "DELETE"):
                        result = request(path, method)
                        assert result["status"] == 404, result
                        rejected.append(result)
        reopening = []
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            reopened = request("/manage/accounts", "POST")
            reopening.append(reopened)
            if reopened["status"] == 200 and reopened["phase"] == "legacy-after": break
            assert reopened["status"] == 403 and reopened["phase"] == "rollback-freeze", reopened
            time.sleep(0.01)
        else: raise AssertionError("legacy admin did not reopen after the completed freeze")
    finally:
        STOP.set()
        if thread.is_alive(): thread.join(timeout=3)
        subprocess.run(["nginx", "-c", "/tmp/receipt-nginx.conf", "-s", "quit"], capture_output=True)
        server.shutdown()
    assert SAMPLES and all(item["status"] == 200 for item in SAMPLES), SAMPLES
    times = sorted(item["milliseconds"] for item in SAMPLES)
    files = ["operations/nginx/routes/phase-4-rollback-freeze.conf", "operations/nginx/routes/phase-0-legacy.conf", "operations/nginx/proxy-common.conf", "operations/scripts/nginx-freeze-barrier.sh"]
    return {"status": "pass", "productionAcceptance": False,
            "scope": "actual-nginx-route-fragments-with-loopback-transport-upstream",
            "applicationSemanticsVerifiedHere": False,
            "sourceSha256": {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files},
            "nginxVersion": subprocess.run(["nginx", "-v"], text=True, capture_output=True).stderr.strip(),
            "durationSeconds": round(time.monotonic()-started, 6), "transitions": transitions,
            "workerBarrierChecks": barrier_checks,
            "continuousReads": len(SAMPLES), "readFailures": 0, "readP95Ms": times[int((len(times)-1)*0.95)],
            "acceptedReads": accepted, "rejectedRequests": rejected,
            "legacyAdminReopenedAfterFreeze": reopened, "reopeningSamples": reopening, "samples": SAMPLES}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
