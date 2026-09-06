package org.mranked.legacyexport.application;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.query.application.CsvExportLimitException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class LegacyCsvService {
    public static final long MAX_ROWS = 2_000_000;
    public static final long MAX_BYTES = 512L * 1024 * 1024;
    private final LegacyCsvRows rows;
    private final DatasetRevisionProvider revisions;
    private final Semaphore generators = new Semaphore(2), artifacts = new Semaphore(4);
    private final ArrayDeque<Long> requests = new ArrayDeque<>();
    private final java.util.Set<Artifact> pending = java.util.concurrent.ConcurrentHashMap.newKeySet();
    private final java.util.concurrent.ScheduledExecutorService expiry = Executors.newSingleThreadScheduledExecutor(task -> {
        var thread = new Thread(task, "legacy-csv-expiry"); thread.setDaemon(true); return thread;
    });
    public LegacyCsvService(LegacyCsvRows rows, DatasetRevisionProvider revisions) {this.rows = rows; this.revisions = revisions;}
    @jakarta.annotation.PreDestroy public void close() {
        expiry.shutdownNow();
        for (var artifact : pending) {try {artifact.close();} catch (IOException ignored) {}}
        pending.clear();
    }

    public record Artifact(DatasetRevision revision, Path path, Semaphore permits,
                           java.util.concurrent.atomic.AtomicBoolean closed) implements AutoCloseable {
        public void transferTo(OutputStream output) throws IOException {
            try (this; var input = Files.newInputStream(path)) {input.transferTo(output);}
        }
        @Override public void close() throws IOException {
            if (closed.compareAndSet(false, true)) {try {Files.deleteIfExists(path);} finally {permits.release();}}
        }
    }
    private synchronized boolean rateAvailable() {
        long now = System.nanoTime();
        while (!requests.isEmpty() && now - requests.getFirst() > TimeUnit.MINUTES.toNanos(1)) requests.removeFirst();
        if (requests.size() >= 20) return false;
        requests.addLast(now); return true;
    }
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, timeout = 300)
    public Artifact prepare(LegacyCsvFormat format) throws IOException {
        if (!rateAvailable() || !generators.tryAcquire()) throw new CsvExportLimitException("Legacy export capacity reached");
        Path path = null; boolean acquired = false;
        try {
            if (!artifacts.tryAcquire()) throw new CsvExportLimitException("Legacy export artifact quota reached");
            acquired = true;
            DatasetRevision revision = revisions.current();
            path = Files.createTempFile("mranked-legacy-export-", ".csv");
            try (var output = Files.newOutputStream(path)) {write(format, revision.id(), output);}
            var result = new Artifact(revision, path, artifacts, new java.util.concurrent.atomic.AtomicBoolean());
            pending.removeIf(artifact -> artifact.closed().get());
            pending.add(result);
            expiry.schedule(() -> {try {result.close();} catch (IOException ignored) {} finally {pending.remove(result);}}, 5, TimeUnit.MINUTES);
            return result;
        } catch (IOException | RuntimeException failure) {
            if (path != null) Files.deleteIfExists(path);
            if (acquired) artifacts.release();
            throw failure;
        } finally {generators.release();}
    }
    public void write(LegacyCsvFormat format, long revision, OutputStream output) throws IOException {
        long started = System.nanoTime(); long[] count = {0};
        var bounded = new java.io.FilterOutputStream(output) {
            private long bytes;
            @Override public void write(int value) throws IOException {
                if (++bytes > MAX_BYTES) throw new CsvExportLimitException("Legacy export exceeds maxBytes");
                out.write(value);
            }
            @Override public void write(byte[] buffer, int offset, int length) throws IOException {
                if ((bytes += length) > MAX_BYTES) throw new CsvExportLimitException("Legacy export exceeds maxBytes");
                out.write(buffer, offset, length);
            }
        };
        var writer = new BufferedWriter(new OutputStreamWriter(bounded, StandardCharsets.UTF_8), 16_384);
        LegacyCsvFormat.writeRecord(writer, format.headers());
        int columns = format.headers().size();
        rows.stream(format, revision, cells -> {
            if (++count[0] > MAX_ROWS) throw new CsvExportLimitException("Legacy export exceeds maxRows");
            if (System.nanoTime() - started > TimeUnit.SECONDS.toNanos(300)) throw new CsvExportLimitException("Legacy export exceeds maxDuration");
            if (cells.size() != columns) throw new IllegalStateException("Legacy export column contract mismatch");
            LegacyCsvFormat.writeRecord(writer, cells);
        });
        writer.flush();
    }
}
