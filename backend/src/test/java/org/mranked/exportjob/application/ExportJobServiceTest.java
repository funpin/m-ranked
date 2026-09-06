package org.mranked.exportjob.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mranked.analytics.domain.Platform;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.query.application.CsvExportLimitException;
import org.mranked.query.application.PublicationCsvRowSource;
import org.mranked.query.application.ResourceNotFoundException;
import org.mranked.query.domain.PublicationCsvRow;

class ExportJobServiceTest {
    @TempDir Path directory;
    static final Instant NOW = Instant.parse("2026-09-05T12:00:00Z");
    static final PublicationCsvRow ROW = new PublicationCsvRow("vk", "=unsafe,\"name\"", UUID.randomUUID(),
            NOW, NOW, 0L, null, 2L, null, "exact");
    static final DatasetRevision REVISION = new DatasetRevision(17, NOW);
    static ExportJobPolicy policy(long rows, long bytes) {
        return new ExportJobPolicy(rows, bytes, Duration.ofSeconds(10), Duration.ofMinutes(1), 1, 4);
    }
    private ExportJobService service(PublicationCsvRowSource rows, DatasetRevisionProvider revisions,
                                     ExportJobPolicy policy, Clock clock) throws IOException {
        return new ExportJobService(new ExportJobGenerator(revisions, rows), revisions, directory, policy, clock);
    }
    static ExportJobService.JobView finished(ExportJobService service, String owner, UUID id) throws Exception {
        long end = System.nanoTime() + TimeUnit.SECONDS.toNanos(15);
        while (System.nanoTime() < end) {
            var result = service.status(owner, id);
            if (result.state() != ExportJobService.State.queued && result.state() != ExportJobService.State.running) return result;
            Thread.sleep(5);
        }
        throw new AssertionError("Export did not finish");
    }

    @Test
    void privateArtifactPinsRevisionPreservesModernCsvAndReleasesDisconnectHandles() throws Exception {
        try (var service = service((platform, revision, rows) -> rows.accept(ROW), () -> REVISION,
                policy(10, 1_000_000), Clock.systemUTC())) {
            var job = service.create("editor", Platform.VK);
            var ready = finished(service, "editor", job.id());
            assertThat(ready.state()).isEqualTo(ExportJobService.State.succeeded);
            assertThat(ready.rowsWritten()).isEqualTo(1);
            assertThat(ready.datasetRevision()).isEqualTo(17);
            assertThatThrownBy(() -> service.status("other-editor", job.id())).isInstanceOf(ResourceNotFoundException.class);
            assertThatThrownBy(() -> service.download("other-editor", job.id())).isInstanceOf(ResourceNotFoundException.class);
            var bytes = new ByteArrayOutputStream();
            service.download("editor", job.id()).transferTo(bytes);
            assertThat(bytes.toString(java.nio.charset.StandardCharsets.UTF_8)).contains("\"'=unsafe,\"\"name\"\"\"")
                    .contains(",0,,2,,exact,17\r\n");
            assertThat(bytes.size()).isEqualTo(ready.bytesWritten());
            for (int retry = 0; retry < 6; retry++) {
                assertThatThrownBy(() -> service.download("editor", job.id()).transferTo(new OutputStream() {
                    @Override public void write(int value) throws IOException { throw new IOException("client disconnected"); }
                    @Override public void write(byte[] value, int offset, int length) throws IOException { throw new IOException("client disconnected"); }
                })).isInstanceOf(IOException.class);
            }
            assertThat(Files.getPosixFilePermissions(directory.resolve("job-" + job.id() + ".csv")))
                    .isEqualTo(java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));
        }
        try (var files = Files.list(directory)) { assertThat(files.filter(path -> path.toString().endsWith(".csv")).count()).isZero(); }
    }

    @Test
    void queuedJobsReserveQuotaAndCancellationDoesNotLeakWorkerOrArtifactCapacity() throws Exception {
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger running = new AtomicInteger(), maxRunning = new AtomicInteger();
        PublicationCsvRowSource rows = (platform, revision, consumer) -> {
            maxRunning.accumulateAndGet(running.incrementAndGet(), Math::max);
            entered.countDown();
            try { release.await(10, TimeUnit.SECONDS); consumer.accept(ROW); }
            catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); throw new java.util.concurrent.CancellationException(); }
            finally { running.decrementAndGet(); }
        };
        try (var service = service(rows, () -> REVISION, policy(10, 1_000_000), Clock.systemUTC())) {
            var first = service.create("a", Platform.VK);
            assertThat(entered.await(5, TimeUnit.SECONDS)).isTrue();
            var queued = service.create("a", Platform.VK);
            service.create("b", Platform.VK); service.create("b", Platform.VK);
            assertThat(service.status("a", queued.id()).state()).isEqualTo(ExportJobService.State.queued);
            assertThatThrownBy(() -> service.create("c", Platform.VK)).isInstanceOf(CsvExportLimitException.class);
            service.cancel("a", queued.id());
            var replacement = service.create("c", Platform.VK);
            service.cancel("a", first.id());
            release.countDown();
            assertThat(finished(service, "c", replacement.id()).state()).isEqualTo(ExportJobService.State.succeeded);
            assertThat(maxRunning).hasValue(1);
        }
    }

    @Test
    void staleQueuedRevisionFailsBeforeAnyRowsAndFailureTextNeverLeaks() throws Exception {
        AtomicInteger revisionReads = new AtomicInteger(), rowReads = new AtomicInteger();
        DatasetRevisionProvider revisions = () -> revisionReads.incrementAndGet() == 1
                ? REVISION : new DatasetRevision(18, NOW);
        try (var service = service((platform, revision, consumer) -> rowReads.incrementAndGet(), revisions,
                policy(10, 1_000_000), Clock.systemUTC())) {
            var job = service.create("editor", Platform.VK);
            var failed = finished(service, "editor", job.id());
            assertThat(failed.state()).isEqualTo(ExportJobService.State.failed);
            assertThat(failed.errorCode()).isEqualTo("REVISION_CHANGED");
            assertThat(rowReads).hasValue(0);
            assertThatThrownBy(() -> service.download("editor", job.id())).isInstanceOf(ExportJobService.ExportNotReadyException.class);
        }
        try (var service = service((platform, revision, consumer) -> { throw new IllegalStateException("password=secret https://private"); },
                () -> REVISION, policy(10, 1_000_000), Clock.systemUTC())) {
            var job = service.create("editor", Platform.VK);
            assertThat(finished(service, "editor", job.id()).errorCode()).isEqualTo("SOURCE_FAILURE");
        }
    }

    @Test
    void rowAndByteCapsFailClosedAndDeletePartialFiles() throws Exception {
        try (var service = service((platform, revision, consumer) -> { consumer.accept(ROW); consumer.accept(ROW); },
                () -> REVISION, policy(1, 1_000_000), Clock.systemUTC())) {
            var job = service.create("editor", Platform.VK);
            assertThat(finished(service, "editor", job.id()).errorCode()).isEqualTo("MAX_ROWS");
        }
        try (var service = service((platform, revision, consumer) -> consumer.accept(ROW), () -> REVISION,
                policy(10, 8), Clock.systemUTC())) {
            var job = service.create("editor", Platform.VK);
            assertThat(finished(service, "editor", job.id()).errorCode()).isEqualTo("MAX_BYTES");
        }
        try (var files = Files.list(directory)) { assertThat(files.filter(path -> path.getFileName().toString().startsWith("job-")).count()).isZero(); }
    }

    @Test
    void durationLimitDeletesPartialArtifact() throws Exception {
        var shortPolicy = new ExportJobPolicy(10, 1_000_000, Duration.ofMillis(20), Duration.ofSeconds(2), 1, 1);
        try (var service = service((platform, revision, consumer) -> {
            try { Thread.sleep(40); } catch (InterruptedException failure) { Thread.currentThread().interrupt(); }
            consumer.accept(ROW);
        }, () -> REVISION, shortPolicy, Clock.systemUTC())) {
            var job = service.create("editor", Platform.VK);
            assertThat(finished(service, "editor", job.id()).errorCode()).isEqualTo("MAX_DURATION");
            assertThat(Files.exists(directory.resolve("job-" + job.id() + ".part"))).isFalse();
        }
    }

    @Test
    void ttlClosesUnstartedDownloadAndDeletesArtifactAndRestartRemovesOrphans() throws Exception {
        MutableClock clock = new MutableClock();
        try (var service = service((platform, revision, consumer) -> consumer.accept(ROW), () -> REVISION,
                policy(10, 1_000_000), clock)) {
            var job = service.create("editor", Platform.VK);
            finished(service, "editor", job.id());
            var abandoned = service.download("editor", job.id());
            clock.now.set(NOW.plusSeconds(61)); service.expire();
            assertThat(service.status("editor", job.id()).state()).isEqualTo(ExportJobService.State.expired);
            assertThat(Files.exists(directory.resolve("job-" + job.id() + ".csv"))).isFalse();
            assertThatThrownBy(() -> abandoned.transferTo(OutputStream.nullOutputStream())).isInstanceOf(IOException.class);
        }
        Path orphan = directory.resolve("job-" + UUID.randomUUID() + ".part"); Files.writeString(orphan, "partial");
        try (var service = service((platform, revision, consumer) -> {}, () -> REVISION,
                policy(10, 1_000_000), Clock.systemUTC())) {
            assertThat(Files.exists(orphan)).isFalse();
            assertThatThrownBy(() -> service((platform, revision, consumer) -> {}, () -> REVISION,
                    policy(10, 1_000_000), Clock.systemUTC())).isInstanceOf(java.nio.channels.OverlappingFileLockException.class);
        }
    }

    @Test
    void largeGenerationCompletesWithAFixedSixtyFourMiBHeap() throws Exception {
        String javaExecutable = Path.of(System.getProperty("java.home"), "bin", "java").toString();
        String classpath = System.getProperty("surefire.test.class.path", System.getProperty("java.class.path"));
        Process process = new ProcessBuilder(javaExecutable, "-Xmx64m", "-cp", classpath,
                ExportHeapProbe.class.getName()).redirectErrorStream(true).start();
        try {
            assertThat(process.waitFor(30, TimeUnit.SECONDS)).isTrue();
            String output = new String(process.getInputStream().readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
            assertThat(process.exitValue()).withFailMessage(output).isZero();
            assertThat(output).contains("\"rows\":600000");
            Path report = Path.of(System.getProperty("mranked.build.directory", "target"), "export-heap.json");
            Files.createDirectories(report.toAbsolutePath().getParent()); Files.writeString(report, output);
        } finally { process.destroyForcibly(); }
    }

    static final class MutableClock extends Clock {
        final AtomicReference<Instant> now = new AtomicReference<>(NOW);
        @Override public ZoneId getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(ZoneId zone) { return this; }
        @Override public Instant instant() { return now.get(); }
    }
}
