# Pinned HTTPS and isolated egress verification

The shared `PinnedHttpsClient` uses Apache HttpClient 5.5.2 from the pinned Spring BOM.
It resolves DNS once per connection, rejects the complete answer set if any address is
private, link-local, loopback, multicast, documentation, or another special-use address,
and supplies those exact `InetAddress` objects to the TCP connection operator. TLS still
validates the original hostname and trusted certificate chain. Connections are not reused;
each redirect therefore receives a fresh validated resolution. There is no runtime switch
to bypass the address policy or trust validation.

Callers pass an exact hostname set on every request and follow redirects explicitly.
HTTPS/443, no userinfo, no fragment and an 8 KiB URL bound are mandatory. Proxy settings,
cookies, automatic retries, redirects and decompression are disabled. Limits include eight
connections, bounded DNS threads/queue, 100 headers, 8 KiB lines, at most 8 MiB plus one
sentinel byte, and a caller deadline up to 30 seconds including DNS and body reading. The
caller rejects an over-limit sentinel body. Socket/body cancellation prevents draining a
large or slow response after the deadline.

Emoji applies its Telegram host allowlist to metadata, selected images and every redirect,
then invokes the same transport. The full chain has one ten-second deadline, 64 KiB
metadata, a 2,000,000-byte image limit and at most 20 redirects. Caffeine bounds successful
assets to 32 MiB of weighted entries for six hours and coalesces concurrent misses for the
same ID. Bytes, browser MIME fallback and the legacy six-hour HTTP cache remain compatible.
No upstream response, DNS result, credential or exception message is returned publicly.

Run the actual DNS/TLS/egress rehearsal with Java 21, Maven, Python and Docker:

```sh
rtk proxy docker pull eclipse-temurin@sha256:7a65df4b22d2de92d4e04056e884f3b9122d70b21e2847fd66084278bd0ce037
rtk proxy .venv/bin/python -m operations.https_egress.rehearse \
  --output /private/tmp/mranked-egress-unique
```

Set `JAVA_HOME`, `MAVEN_USER_HOME` and optional `MRANKED_MAVEN_REPOSITORY` for the local
toolchain. The runner builds the real client and tests, copies only classpath artifacts,
and runs the same evidence producer in a non-root container with `--network none`, no
capabilities, a read-only root, 128 MiB heap, 384 MiB memory and bounded `/tmp`. Only its own
UUID container is removed afterward. The immutable image digest is recorded in the report.

The producer uses real loopback UDP DNS and a TLS server with an ephemeral certificate.
It tests exact image bytes, one checked DNS resolution per connect, manual redirects,
blocked private redirects, invalid URL corpus, TLS hostname mismatch, mixed answer sets,
DNS rebinding between hops, byte/header bounds and slow-body cancellation. A test-only
constructor permits exactly `127.0.0.1` for positive fixtures; the production policy is
separately proven to reject that same answer before HTTP. The container must have no active
non-loopback interface, and an attempted TEST-NET TCP connection must fail at the kernel.

Keep `https-egress.json`, its SHA-256 sidecar, Markdown summary and inner network report.
The private fixture key is deleted immediately after loading; build directories and JARs
are runtime artifacts, not release evidence.

Production acceptance remains **NO-GO** until a separately authorized deployment validates
the actual Telegram/CDN responses and production egress enforcement. An application allowlist
does not replace a firewall/proxy. A production policy must deny private/special destinations
for the API identity, allow only approved DNS and HTTPS egress, preserve TLS peer validation,
and be tested from the deployed network namespace. The local network-none policy demonstrates
enforcement and cannot itself be deployed unchanged while live providers are required. This
runner never changes production Nginx, DNS, firewall rules or upstreams.
