package org.mranked.exportjob.application;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.io.OutputStream;
import java.net.URI;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import javax.sql.DataSource;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.mranked.analytics.domain.Platform;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.infrastructure.JdbcDatasetRevisionProvider;
import org.mranked.query.application.PublicationCsvRowSource;
import org.mranked.query.infrastructure.JdbcPublicationCsvRowSource;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.AbstractDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;

@EnabledIfEnvironmentVariable(named = "MRANKED_EXPORT_TEST_ADMIN_URL", matches = ".+")
class ExportJobPostgresIntegrationTest {
    @TempDir Path spool;
    static final int ROWS = 150_001;
    static final Instant PUBLISHED = Instant.parse("2026-08-01T12:00:00Z");

    @Test
    void largeCursorRetainsOneSnapshotAcrossConcurrentPublicationAndCancelReleasesConnection() throws Exception {
        long started = System.nanoTime();
        long[] exportedBytes = {0};
        String initial = System.getenv("MRANKED_EXPORT_TEST_ADMIN_URL");
        URI uri = URI.create(initial.substring("jdbc:".length()));
        assertThat(uri.getHost()).isIn("127.0.0.1", "localhost", "[::1]");
        assertThat(uri.getPath()).endsWith("_it");
        String name = "mranked_export_" + UUID.randomUUID().toString().replace("-", "") + "_it";
        String url = "jdbc:" + new URI(uri.getScheme(), null, uri.getHost(), uri.getPort(), "/" + name, uri.getQuery(), null);
        String owner = System.getenv("MRANKED_EXPORT_TEST_ADMIN_USERNAME"), password = System.getenv("MRANKED_EXPORT_TEST_ADMIN_PASSWORD");
        try (var control = DriverManager.getConnection(initial, owner, password)) {
            control.createStatement().execute("CREATE DATABASE " + name + " OWNER migration_owner");
            try {
                Flyway.configure().dataSource(url, owner, password).initSql("SET ROLE migration_owner")
                        .defaultSchema("flyway").locations("classpath:db/migration").cleanDisabled(true).load().migrate();
                try (var seed = DriverManager.getConnection(url, owner, password); var statement = seed.createStatement()) {
                    statement.execute("""
                        INSERT INTO catalog.institution(id,canonical_name) VALUES ('00000000-0000-0000-0000-000000000017',repeat('I',200));
                        INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
                        VALUES ('00000000-0000-0000-0000-000000000018','00000000-0000-0000-0000-000000000017','vk','export-fixture','public_web');
                        INSERT INTO analytics.dataset_revision(id,cause,correlation_id) VALUES (17,'migration',gen_random_uuid());
                        INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness)
                        SELECT md5('publication-'||i)::uuid,'00000000-0000-0000-0000-000000000018',
                            timestamptz '2026-08-01 12:00:00Z'+i*interval '1 second',now(),'post','incomplete'
                        FROM generate_series(1,150001) i;
                        INSERT INTO analytics.publication_latest(publication_id,institution_id,platform_account_id,platform,observed_at,
                            views_count,views_observed_at,views_quality,quality,history_completeness,dataset_revision_id)
                        SELECT id,'00000000-0000-0000-0000-000000000017',primary_account_id,'vk',published_at,
                            7,published_at,'exact','exact','incomplete',17 FROM ingest.publication;
                        INSERT INTO analytics.projection_state(projection_name,dataset_revision_id,status,refreshed_at,row_count)
                        SELECT projection,17,'ready',now(),150001 FROM (VALUES ('publication_latest'),('publication_hourly'),
                            ('institution_daily_metrics'),('institution_monthly_metrics'),('institution_period_metrics'),('comparison'),
                            ('publication_history'),('publication_content'),('legacy_exports')) names(projection);
                        """);
                }
                var source = new TrackingDataSource(new DriverManagerDataSource(url, "api_read", System.getenv("MRANKED_QUERY_TEST_PASSWORD")));
                var delegateRevisions = new JdbcDatasetRevisionProvider(JdbcClient.create(source));
                CountDownLatch pinned = new CountDownLatch(1), mutated = new CountDownLatch(1), rowPaused = new CountDownLatch(1);
                AtomicInteger revisionReads = new AtomicInteger();
                AtomicBoolean pauseNextRow = new AtomicBoolean();
                DatasetRevisionProvider revisions = () -> {
                    var revision = delegateRevisions.current();
                    if (revisionReads.incrementAndGet() == 2) {
                        pinned.countDown();
                        try { if (!mutated.await(15, TimeUnit.SECONDS)) throw new AssertionError("Mutation did not finish"); }
                        catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new CancellationException(); }
                    }
                    return revision;
                };
                var jdbcRows = new JdbcPublicationCsvRowSource(source);
                PublicationCsvRowSource rows = new PublicationCsvRowSource() {
                    @Override public void stream(Platform platform, long revision, CsvRowConsumer consumer) throws IOException {
                        streamBounded(platform, revision, 2_000_000, 300, consumer);
                    }
                    @Override public void streamBounded(Platform platform, long revision, long limit, int timeout, CsvRowConsumer consumer) throws IOException {
                        jdbcRows.streamBounded(platform, revision, limit, timeout, row -> {
                            if (pauseNextRow.compareAndSet(true, false)) {
                                rowPaused.countDown();
                                try { Thread.sleep(10_000); }
                                catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new CancellationException(); }
                            }
                            consumer.accept(row);
                        });
                    }
                };
                ProxyFactory factory = new ProxyFactory(new ExportJobGenerator(revisions, rows));
                factory.addAdvice(new TransactionInterceptor(new DataSourceTransactionManager(source), new AnnotationTransactionAttributeSource()));
                var generator = (ExportJobGenerator) factory.getProxy();
                try (var jobs = new ExportJobService(generator, revisions, spool, ExportJobPolicy.defaults(), Clock.systemUTC())) {
                    var job = jobs.create("editor", Platform.VK);
                    assertThat(pinned.await(5, TimeUnit.SECONDS)).isTrue();
                    assertThat(source.active).hasValue(1);
                    try (var mutation = DriverManager.getConnection(url, owner, password); var statement = mutation.createStatement()) {
                        statement.execute("""
                            BEGIN;
                            INSERT INTO analytics.dataset_revision(id,cause,correlation_id) VALUES (18,'migration',gen_random_uuid());
                            UPDATE catalog.institution SET canonical_name='changed after export snapshot';
                            UPDATE analytics.publication_latest SET views_count=999,dataset_revision_id=18;
                            UPDATE analytics.projection_state SET dataset_revision_id=18;
                            COMMIT;
                            """);
                    } finally { mutated.countDown(); }
                    var ready = ExportJobServiceTest.finished(jobs, "editor", job.id());
                    assertThat(ready.state()).isEqualTo(ExportJobService.State.succeeded);
                    assertThat(ready.rowsWritten()).isEqualTo(ROWS);
                    assertThat(ready.bytesWritten()).isGreaterThan(32L * 1024 * 1024);
                    exportedBytes[0] = ready.bytesWritten();
                    CsvVerifier verifier = new CsvVerifier(); jobs.download("editor", job.id()).transferTo(verifier);
                    assertThat(verifier.rows).isEqualTo(ROWS);
                    assertThat(source.active).hasValue(0);
                    assertThat(source.maximum).hasValue(1);
                    assertThat(source.repeatableRead.get()).isTrue();
                    pauseNextRow.set(true);
                    var cancel = jobs.create("another-editor", Platform.VK);
                    assertThat(rowPaused.await(5, TimeUnit.SECONDS)).isTrue();
                    jobs.cancel("another-editor", cancel.id());
                    long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
                    while (source.active.get() != 0 && System.nanoTime() < deadline) Thread.sleep(5);
                    assertThat(source.active).hasValue(0);
                    assertThat(jobs.status("another-editor", cancel.id()).state()).isEqualTo(ExportJobService.State.cancelled);
                }
            } finally { control.createStatement().execute("DROP DATABASE " + name + " WITH (FORCE)"); }
        }
        Path report = Path.of(System.getProperty("mranked.build.directory", "target"), "export-postgres.json");
        java.nio.file.Files.createDirectories(report.toAbsolutePath().getParent());
        java.nio.file.Files.writeString(report, "{\"status\":\"pass\",\"rows\":" + ROWS
                + ",\"bytes\":" + exportedBytes[0] + ",\"maxConnections\":1,\"repeatableRead\":true,"
                + "\"fixedRevision\":17,\"concurrentPublishedRevision\":18,\"sameSnapshotVerified\":true,"
                + "\"cancelReleasedConnection\":true,\"ownedDatabaseDropped\":true,\"durationSeconds\":"
                + (System.nanoTime() - started) / 1_000_000_000.0 + "}\n");
    }

    private static final class CsvVerifier extends OutputStream {
        private final StringBuilder line = new StringBuilder(512);
        int rows = -1;
        @Override public void write(int value) {
            if (value == '\n') {
                if (rows >= 0) {
                    String[] columns = line.toString().stripTrailing().split(",", -1);
                    assertThat(columns[1]).isEqualTo("I".repeat(200));
                    assertThat(Instant.parse(columns[3])).isEqualTo(PUBLISHED.plusSeconds(rows + 1L));
                    assertThat(columns[5]).isEqualTo("7");
                    assertThat(columns[10]).isEqualTo("17");
                }
                rows++; line.setLength(0);
            } else {
                if (line.length() > 1024) throw new AssertionError("Unexpected oversized fixture row");
                line.append((char) value);
            }
        }
    }

    private static final class TrackingDataSource extends AbstractDataSource {
        final DataSource delegate;
        final AtomicInteger active = new AtomicInteger(), maximum = new AtomicInteger();
        final AtomicBoolean repeatableRead = new AtomicBoolean();
        TrackingDataSource(DataSource delegate) { this.delegate = delegate; }
        @Override public Connection getConnection() throws java.sql.SQLException {
            Connection connection = delegate.getConnection(); maximum.accumulateAndGet(active.incrementAndGet(), Math::max);
            AtomicBoolean closed = new AtomicBoolean();
            return (Connection) java.lang.reflect.Proxy.newProxyInstance(getClass().getClassLoader(), new Class<?>[]{Connection.class}, (proxy, method, args) -> {
                if (method.getName().equals("close") && closed.compareAndSet(false, true)) active.decrementAndGet();
                if (method.getName().equals("setTransactionIsolation") && (int) args[0] == Connection.TRANSACTION_REPEATABLE_READ) repeatableRead.set(true);
                try { return method.invoke(connection, args); }
                catch (java.lang.reflect.InvocationTargetException failure) { throw failure.getCause(); }
            });
        }
        @Override public Connection getConnection(String username, String password) throws java.sql.SQLException { return getConnection(); }
    }
}
