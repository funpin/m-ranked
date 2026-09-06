package org.mranked.operations.infrastructure;

import java.io.IOException;
import java.net.InetAddress;
import java.net.URI;
import java.net.UnknownHostException;
import java.util.concurrent.*;
import java.util.function.Predicate;
import javax.net.ssl.SSLContext;
import org.apache.hc.client5.http.DnsResolver;
import org.apache.hc.client5.http.classic.methods.HttpGet;
import org.apache.hc.client5.http.config.ConnectionConfig;
import org.apache.hc.client5.http.config.RequestConfig;
import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManagerBuilder;
import org.apache.hc.client5.http.ssl.ClientTlsStrategyBuilder;
import org.apache.hc.core5.util.Timeout;

/** The connection operator receives validated InetAddress objects, so it never resolves a
 * hostname again between validation and TCP connect. TLS still verifies the original hostname.
 * No user proxy, redirects, cookies, credentials, decompression or retries are inherited. */
public final class PinnedHttpsClient implements AutoCloseable {
    private final CloseableHttpClient client;
    private final ThreadLocal<Long> requestDeadline = new ThreadLocal<>();
    private final ScheduledExecutorService deadlines = Executors.newSingleThreadScheduledExecutor(
            runnable -> { var thread = new Thread(runnable, "https-deadlines"); thread.setDaemon(true); return thread; });
    private final ThreadPoolExecutor dns = new ThreadPoolExecutor(2, 8, 30, TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(16), runnable -> {
                var thread = new Thread(runnable, "https-dns"); thread.setDaemon(true); return thread;
            }, new ThreadPoolExecutor.AbortPolicy());

    public PinnedHttpsClient() {
        this(InetAddress::getAllByName, PublicAddressPolicy::allowed, null, 443);
    }

    // Package-private injection exists solely for isolated local DNS/TLS tests. There is no
    // deployment property that can permit a private IP, change the HTTPS port or bypass TLS.
    PinnedHttpsClient(Lookup lookup, Predicate<InetAddress> addresses, SSLContext trust, int tlsPort) {
        DnsResolver resolver = new DnsResolver() {
            public InetAddress[] resolve(String host) throws UnknownHostException {
                Future<InetAddress[]> task;
                try { task = dns.submit(() -> lookup.resolve(host)); }
                catch (RejectedExecutionException failure) { throw new UnknownHostException("https DNS capacity exceeded"); }
                try {
                    Long deadline = requestDeadline.get();
                    long remaining = deadline == null ? TimeUnit.SECONDS.toNanos(10) : deadline - System.nanoTime();
                    if (remaining <= 0) throw new TimeoutException();
                    InetAddress[] result = task.get(remaining, TimeUnit.NANOSECONDS);
                    if (result == null || result.length == 0 || result.length > 32)
                        throw new UnknownHostException("https DNS answer count is invalid");
                    for (InetAddress address : result)
                        if (!addresses.test(address)) throw new UnknownHostException("https DNS address is prohibited");
                    return result.clone();
                } catch (ExecutionException | TimeoutException failure) {
                    throw new UnknownHostException("https DNS resolution failed");
                } catch (InterruptedException failure) {
                    Thread.currentThread().interrupt();
                    throw new UnknownHostException("https DNS resolution interrupted");
                } finally { task.cancel(true); }
            }
            public String resolveCanonicalHostname(String host) { return host; }
        };
        var tls = ClientTlsStrategyBuilder.create();
        if (trust != null) tls.setSslContext(trust);
        var manager = PoolingHttpClientConnectionManagerBuilder.create()
                .setConnectionFactory(org.apache.hc.client5.http.impl.io.ManagedHttpClientConnectionFactory.builder()
                        .http1Config(org.apache.hc.core5.http.config.Http1Config.custom()
                                .setMaxHeaderCount(100).setMaxLineLength(8192).build()).build())
                .setDnsResolver(resolver).setSchemePortResolver((host) -> tlsPort)
                .setTlsSocketStrategy(tls.buildClassic()).setMaxConnTotal(8).setMaxConnPerRoute(8)
                .setDefaultConnectionConfig(ConnectionConfig.custom().setConnectTimeout(Timeout.ofSeconds(10))
                        .setSocketTimeout(Timeout.ofSeconds(10)).build()).build();
        client = HttpClients.custom().setConnectionManager(manager)
                .setConnectionReuseStrategy((request, response, context) -> false)
                .disableRedirectHandling().disableAutomaticRetries().disableCookieManagement()
                .disableContentCompression().disableAuthCaching()
                .setDefaultRequestConfig(RequestConfig.custom().setConnectionRequestTimeout(Timeout.ofSeconds(1))
                        .setResponseTimeout(Timeout.ofSeconds(10)).build()).build();
    }

    public Response fetch(URI uri, int maximumBytes, java.time.Duration timeoutDuration, java.util.Set<String> allowedHosts) throws IOException {
        long remainingNanos = timeoutDuration.toNanos();
        if (uri == null || uri.toASCIIString().length()>8192 || !"https".equals(uri.getScheme()) || uri.getHost() == null
                || uri.getRawUserInfo() != null || uri.getRawFragment() != null
                || uri.getPort() != -1 && uri.getPort() != 443
                || !allowedHosts.contains(uri.getHost().toLowerCase(java.util.Locale.ROOT))
                || maximumBytes < 0 || maximumBytes > 8 * 1024 * 1024
                || remainingNanos <= 0 || remainingNanos > TimeUnit.SECONDS.toNanos(30))
            throw new IOException("HTTPS request is prohibited or expired");
        HttpGet request = new HttpGet(uri);
        request.setHeader("Accept", "application/json,image/webp,image/png,image/gif,image/jpeg,*/*");
        request.setHeader("Connection", "close");
        var timeout = deadlines.schedule(request::cancel, remainingNanos, TimeUnit.NANOSECONDS);
        requestDeadline.set(System.nanoTime() + remainingNanos);
        try {
            return client.execute(request, response -> {
                var entity = response.getEntity();
                byte[] body;
                if (entity == null) body = new byte[0];
                else try (var input = entity.getContent()) {
                    body = input.readNBytes(maximumBytes + 1);
                    // Cancel before closing an oversized entity; never drain an unbounded body.
                    if (body.length > maximumBytes) request.cancel();
                }
                var location = response.getFirstHeader("Location");
                var contentType = response.getFirstHeader("Content-Type");
                return new Response(response.getCode(),
                        location == null ? null : location.getValue(), contentType == null ? "" : contentType.getValue(), body);
            });
        } finally { timeout.cancel(false); requestDeadline.remove(); }
    }

    @Override public void close() throws IOException {
        deadlines.shutdownNow(); dns.shutdownNow(); client.close();
    }

    public record Response(int statusCode, String location, String contentType, byte[] body) {}

    @FunctionalInterface interface Lookup { InetAddress[] resolve(String host) throws UnknownHostException; }
}
