"""Проверка на браузер (operations/nginx/pass.js) в настоящем nginx с njs.

Поднимает образ nginx:1.26.3 (в нём есть ngx_http_js_module) с конфигурацией
сайта из репозитория и заглушкой вместо Next, которая считает рендеры. Нет
Docker или образа локально — тест пропускается: образ не скачивается.
"""
from __future__ import annotations

import hashlib
import http.server
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NGINX = ROOT / "operations" / "nginx"
IMAGE = "nginx:1.26.3"
CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/110.0.0.0 Safari/537.36")
GOOGLE = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
CRAWLER = ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Reflectionbot/1.0; "
           "+https://reflection.ai/bot) Chrome/151.0.0.0 Safari/537.36")
META_INDEXER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36 (compatible; meta-webindexer/1.1 "
                "(+https://developers.facebook.com/docs/sharing/webmasters/crawler))")
BITS = 10


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(not _docker_ready(), reason=f"нужен Docker и локальный образ {IMAGE}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Stub(http.server.BaseHTTPRequestHandler):
    """Вместо Next: HTML страницы, срок кэша из ?ttl=, счёт рендеров по пути."""
    renders: Counter = Counter()

    def do_GET(self) -> None:  # noqa: N802 - имя из http.server
        path = urllib.parse.urlsplit(self.path).path
        Stub.renders[path] += 1
        ttl = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("ttl", ["60"])[0]
        body = f"<html><body>page {path}</body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Accel-Expires", ttl)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    stub = http.server.ThreadingHTTPServer(("0.0.0.0", 0), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    conf = tmp_path_factory.mktemp("nginx")
    inner = conf / "m-ranked"
    inner.mkdir()
    for path in NGINX.iterdir():
        if path.suffix in (".conf", ".js"):
            text = path.read_text(encoding="utf-8").replace("/etc/m-ranked/nginx", "/etc/m-ranked-test/m-ranked")
            (inner / path.name).write_text(text, encoding="utf-8")
    (inner / "build.conf").write_text('map $host $m_ranked_build { default "test"; }\n', encoding="utf-8")
    (inner / "pass-secret.conf").write_text('map "" $m_ranked_pass_secret { default "' + "ab" * 32 + '"; }\n',
                                            encoding="utf-8")
    # Лимит по странам: все «свои»; тест лимита помечает «чужим» адрес самого
    # контейнера и перечитывает конфигурацию.
    (inner / "geo-home.conf").write_text("geo $http_x_mranked_client $m_ranked_home_country { default 1; }\n",
                                         encoding="utf-8")
    upstream = f"host.docker.internal:{stub.server_address[1]}"
    (conf / "nginx.conf").write_text(f"""
load_module /usr/lib/nginx/modules/ngx_http_js_module.so;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;
worker_processes 1;
events {{ worker_connections 256; }}
http {{
    upstream m_ranked_web {{ server {upstream}; keepalive 4; }}
    upstream m_ranked_api {{ server {upstream}; keepalive 4; }}
    include /etc/nginx/mime.types;
    include /etc/m-ranked-test/m-ranked/traffic.conf;
    server {{
        listen 8080;
        server_name m.test;
        include /etc/m-ranked-test/m-ranked/site.conf;
    }}
}}
""", encoding="utf-8")
    port = _free_port()
    container = subprocess.run(
        ["docker", "run", "-d", "--add-host=host.docker.internal:host-gateway",
         "-p", f"127.0.0.1:{port}:8080", "-v", f"{conf}:/etc/m-ranked-test:ro", IMAGE,
         "nginx", "-g", "daemon off;", "-c", "/etc/m-ranked-test/nginx.conf"],
        capture_output=True, text=True, check=True).stdout.strip()
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/robots.txt", timeout=1)
                break
            except urllib.error.HTTPError:
                break
            except OSError:
                time.sleep(0.1)
        else:
            logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True)
            pytest.fail("nginx не поднялся:\n" + logs.stdout + logs.stderr)
        yield base, container, inner
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        stub.shutdown()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get(url: str, *, agent: str = CHROME, cookie: str | None = None, headers: dict | None = None):
    request = urllib.request.Request(url, headers={"User-Agent": agent, **(headers or {})})
    if cookie:
        request.add_header("Cookie", cookie)
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode()


def solve(challenge: str) -> int:
    for nonce in range(10_000_000):
        digest = hashlib.sha256(f"{challenge}:{nonce}".encode()).digest()
        if int.from_bytes(digest[:2], "big") >> (16 - BITS) == 0:
            return nonce
    raise AssertionError("задача не решается")


def pass_cookie(base: str, path: str) -> str:
    status, headers, body = get(base + path)
    assert status == 429, body
    challenge = re.search(r'var c="([^"]+)"', body).group(1)
    status, headers, _ = get(f"{base}/__pass?c={challenge}&n={solve(challenge)}&to={urllib.parse.quote(path)}")
    assert status == 303 and headers["Location"] == path
    cookie = headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Lax" in cookie
    return cookie.split(";", 1)[0]


def test_anonymous_miss_gets_challenge_not_render(site):
    base, _, _ = site
    status, headers, body = get(base + "/publications/a1")
    assert status == 429
    assert Stub.renders["/publications/a1"] == 0
    assert "X-Accel-Expires" not in headers or headers.get("Cache-Control") == "no-store"
    assert "script-src 'nonce-" in headers["Content-Security-Policy"]
    # Задача не попадает в кэш: второй раз — снова задача, рендеров нет.
    assert get(base + "/publications/a1")[0] == 429
    assert Stub.renders["/publications/a1"] == 0


def test_solved_challenge_gives_cookie_and_page_is_then_cached_for_everyone(site):
    base, _, _ = site
    cookie = pass_cookie(base, "/publications/b2")
    status, headers, body = get(base + "/publications/b2", cookie=cookie)
    assert status == 200 and "page /publications/b2" in body
    assert Stub.renders["/publications/b2"] == 1
    # Готовая страница из кэша достаётся и посетителю без куки — бесплатно.
    status, headers, body = get(base + "/publications/b2")
    assert status == 200 and headers["X-Cache-Status"] == "HIT"
    assert Stub.renders["/publications/b2"] == 1


def test_stale_copy_beats_challenge(site):
    base, _, _ = site
    cookie = pass_cookie(base, "/accounts/c3")
    assert get(base + "/accounts/c3?ttl=1", cookie=cookie)[0] == 200
    time.sleep(2.5)  # срок в nginx — целые секунды: «1» живёт до двух
    status, headers, body = get(base + "/accounts/c3?ttl=1")
    assert status == 200 and headers["X-Cache-Status"] == "STALE"


def test_app_cache_lifetime_reaches_the_public_layer(site):
    """Срок из X-Accel-Expires приложения доходит через шлюз до кэша страниц:
    через 6 с (дольше запасных 5 с) страница всё ещё свежая, без рендера."""
    base, _, _ = site
    cookie = pass_cookie(base, "/accounts/k9")
    assert get(base + "/accounts/k9?ttl=60", cookie=cookie)[0] == 200
    time.sleep(6)
    status, headers, _ = get(base + "/accounts/k9?ttl=60")
    assert status == 200 and headers["X-Cache-Status"] == "HIT"
    assert Stub.renders["/accounts/k9"] == 1


def test_rsc_navigation_without_cookie_is_challenged_and_prefetch_is_not(site):
    base, _, _ = site
    assert get(base + "/institutions/4", headers={"RSC": "1"})[0] == 429
    assert get(base + "/institutions/5", headers={"Next-Router-Prefetch": "1", "RSC": "1"})[0] == 200


def test_search_engines_and_next_files_are_not_challenged(site):
    base, _, _ = site
    assert get(base + "/publications/d4", agent=GOOGLE)[0] == 200
    assert get(base + "/_next/data/x.json")[0] == 200


def test_forged_or_expired_tokens_are_rejected(site):
    base, _, _ = site
    assert get(base + "/publications/e5", cookie="mr_pass=9999999999.forged")[0] == 429
    status, _, body = get(base + "/publications/e5")
    challenge = re.search(r'var c="([^"]+)"', body).group(1)
    wrong = next(n for n in range(100) if hashlib.sha256(f"{challenge}:{n}".encode()).digest()[0] != 0)
    assert get(f"{base}/__pass?c={challenge}&n={wrong}&to=/x")[0] == 403
    head, tail = challenge.rsplit(".", 1)
    assert get(f"{base}/__pass?c={head}.AAAA&n=0&to=/x")[0] == 403


def test_pass_redirect_stays_on_site(site):
    base, _, _ = site
    _, _, body = get(base + "/publications/f6")
    challenge = re.search(r'var c="([^"]+)"', body).group(1)
    nonce = solve(challenge)
    for target in ("//evil.example/x", "/\\evil.example", "https://evil.example/"):
        status, headers, _ = get(f"{base}/__pass?c={challenge}&n={nonce}&to={urllib.parse.quote(target, safe='')}")
        assert status == 303 and headers["Location"] == "/"


def test_requests_from_the_server_itself_are_not_challenged(site):
    _, container, _ = site
    probe = subprocess.run(["docker", "exec", container, "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                            "-A", CHROME, "http://127.0.0.1:8080/publications/g7"],
                           capture_output=True, text=True)
    assert probe.stdout == "200"


def test_challenge_page_solves_in_a_real_browser(site):
    playwright = pytest.importorskip("playwright.sync_api")
    base, _, _ = site
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as error:  # noqa: BLE001 - нет браузера Playwright — пропускаем
            pytest.skip(f"нет Chromium для Playwright: {error}")
        page = browser.new_page()
        start = time.monotonic()
        page.goto(base + "/publications/h8")
        page.wait_for_url(base + "/publications/h8", timeout=10_000)
        page.wait_for_selector("text=page /publications/h8", timeout=10_000)
        assert time.monotonic() - start < 5
        browser.close()


def test_challenge_overhead_in_chromium(site):
    """Цена проверки для человека: первое открытие (задача + /__pass + страница)
    против следующей холодной страницы с кукой. Печатает медианы (pytest -s)."""
    playwright = pytest.importorskip("playwright.sync_api")
    base, _, _ = site
    first, again = [], []
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as error:  # noqa: BLE001
            pytest.skip(f"нет Chromium для Playwright: {error}")
        for index in range(8):
            context = browser.new_context()
            page = context.new_page()
            for bucket, path in ((first, f"/publications/m{index}"), (again, f"/publications/m{index}x")):
                start = time.monotonic()
                page.goto(base + path)
                page.wait_for_selector(f"text=page {path}")
                bucket.append(time.monotonic() - start)
            context.close()
        browser.close()
    first.sort(), again.sort()
    print(f"\nпервое открытие с проверкой: медиана {first[4] * 1000:.0f} мс, макс {first[-1] * 1000:.0f} мс; "
          f"холодная страница с кукой: медиана {again[4] * 1000:.0f} мс, макс {again[-1] * 1000:.0f} мс")
    assert first[4] < 2.0


def _foreign_rejections(container: str) -> int:
    logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True)
    return (logs.stdout + logs.stderr).count('by zone "m_ranked_foreign_detail"')


def test_foreign_visitors_with_cookie_share_a_cold_page_limit(site):
    """Чужая страна с кукой: свой общий лимит (10/мин, всплеск 10) — его отказы
    видны в журнале по имени зоны. Свой посетитель в эту зону не попадает."""
    base, container, inner = site
    cookie = pass_cookie(base, "/publications/geo0")
    address = subprocess.run(["docker", "exec", container, "sh", "-c", "hostname -i | cut -d' ' -f1"],
                             capture_output=True, text=True, check=True).stdout.strip()
    (inner / "geo-home.conf").write_text(
        f"geo $http_x_mranked_client $m_ranked_home_country {{ default 1; {address}/32 0; }}\n", encoding="utf-8")
    subprocess.run(["docker", "exec", container, "nginx", "-s", "reload", "-c", "/etc/m-ranked-test/nginx.conf"],
                   capture_output=True, check=True)
    time.sleep(1)
    before = _foreign_rejections(container)
    # Не чаще 2 в секунду: иначе раньше сработает лимит промахов на адрес.
    script = (f'for i in $(seq 1 25); do curl -s -o /dev/null -w "%{{http_code}}\\n" -A "{CHROME}" '
              f'-H "Cookie: {cookie}" http://{address}:8080/publications/geo-$i; sleep 0.55; done')
    codes = subprocess.run(["docker", "exec", container, "sh", "-c", script],
                           capture_output=True, text=True, check=True).stdout.split()
    assert codes.count("200") <= 13 and codes.count("503") >= 12, codes
    assert _foreign_rejections(container) > before
    seen = _foreign_rejections(container)
    for i in range(5):
        get(f"{base}/publications/home-{i}", cookie=cookie)
        time.sleep(0.55)
    assert _foreign_rejections(container) == seen


def test_crawlers_get_a_page_budget_and_search_engines_keep_their_own(site):
    """31.10.2026 обход meta-webindexer на четырёх общих рендерах занял оба ядра.
    Теперь у прочих роботов 12 холодных страниц в минуту (всплеск 5) — сверх
    этого сразу 503 с Retry-After, а поисковики выдачи считаются отдельно."""
    base, _, _ = site
    answers = [get(f"{base}/publications/crawl-{i}", agent=CRAWLER) for i in range(10)]
    codes = [status for status, _, _ in answers]
    assert codes[:6] == [200] * 6 and codes[-1] == 503, codes
    assert answers[-1][1].get("Retry-After") == "120"
    assert [get(f"{base}/publications/search-{i}", agent=GOOGLE)[0] for i in range(5)] == [200] * 5


def test_meta_ai_search_indexer_is_closed_like_other_ai_search(site):
    base, _, _ = site
    assert get(base + "/publications/meta-1", agent=META_INDEXER)[0] == 403
    assert get(base + "/robots.txt", agent=META_INDEXER)[0] == 200
