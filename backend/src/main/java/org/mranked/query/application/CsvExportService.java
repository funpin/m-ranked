package org.mranked.query.application;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.mranked.analytics.domain.Platform;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.query.domain.PublicationCsvRow;
import org.springframework.stereotype.Service;

@Service
public class CsvExportService {
    public static final long MAX_ROWS = 100_000;
    public static final long MAX_BYTES = 32L * 1024 * 1024;
    public static final java.time.Duration MAX_DURATION = java.time.Duration.ofSeconds(30);
    private final java.util.concurrent.Semaphore generationSlots = new java.util.concurrent.Semaphore(2);
    private final java.util.concurrent.Semaphore downloadSlots = new java.util.concurrent.Semaphore(4);
    private final java.util.concurrent.ScheduledExecutorService expiry = java.util.concurrent.Executors.newSingleThreadScheduledExecutor(
            task -> { Thread thread = new Thread(task, "public-export-expiry"); thread.setDaemon(true); return thread; });
    @jakarta.annotation.PreDestroy void shutdown() { expiry.shutdownNow(); }
    private final java.util.ArrayDeque<Long> recentExports = new java.util.ArrayDeque<>();

    public record PreparedExport(DatasetRevision revision, java.nio.file.Path path,
                                 java.util.concurrent.Semaphore slots) implements AutoCloseable {
        public void transferTo(OutputStream output) throws IOException {
            try (this; var input = java.nio.file.Files.newInputStream(path)) { input.transferTo(output); }
        }
        @Override public void close() throws IOException {
            if (java.nio.file.Files.deleteIfExists(path)) slots.release();
        }
    }

    private synchronized boolean permitRequest() {
        long now = System.nanoTime();
        while (!recentExports.isEmpty() && now - recentExports.peekFirst() > 60_000_000_000L) recentExports.removeFirst();
        if (recentExports.size() >= 10) return false;
        recentExports.addLast(now);
        return true;
    }

    @org.springframework.transaction.annotation.Transactional(readOnly = true,
            isolation = org.springframework.transaction.annotation.Isolation.REPEATABLE_READ, timeout = 30)
    public PreparedExport prepare(Platform platform) throws IOException {
        if (!permitRequest()) throw new CsvExportLimitException("Export rate limit reached; retry later");
        if (!generationSlots.tryAcquire()) throw new CsvExportLimitException("Export capacity reached; retry later");
        boolean artifactSlot = false;
        java.nio.file.Path path = null;
        try {
            if (!downloadSlots.tryAcquire()) throw new CsvExportLimitException("Export download capacity reached; retry later");
            artifactSlot = true;
            DatasetRevision revision = revisionProvider.current();
            path = java.nio.file.Files.createTempFile("mranked-public-export-", ".csv");
            try (var output = java.nio.file.Files.newOutputStream(path)) { write(platform, revision, output); }
            var artifact = new PreparedExport(revision, path, downloadSlots);
            expiry.schedule(() -> { try { artifact.close(); } catch (IOException ignored) { } },
                    5, java.util.concurrent.TimeUnit.MINUTES);
            return artifact;
        } catch (IOException | RuntimeException exception) {
            if (path != null) java.nio.file.Files.deleteIfExists(path);
            if (artifactSlot) downloadSlots.release();
            throw exception;
        } finally { generationSlots.release(); }
    }

    public static final List<String> HEADERS = List.of(
            "platform", "institution", "publication_id", "published_at", "observed_at",
            "views", "reactions", "comments", "shares", "quality", "dataset_revision"
    );

    private final PublicationCsvRowSource rowSource;
    private final DatasetRevisionProvider revisionProvider;

    public CsvExportService(
            PublicationCsvRowSource rowSource,
            DatasetRevisionProvider revisionProvider
    ) {
        this.rowSource = rowSource;
        this.revisionProvider = revisionProvider;
    }

    public DatasetRevision currentRevision() {
        return revisionProvider.current();
    }

    public void write(Platform platform, DatasetRevision revision, OutputStream output) throws IOException {
        long started = System.nanoTime();
        long[] rows = {0};
        OutputStream bounded = new java.io.FilterOutputStream(output) {
            private long bytes;
            @Override public void write(int value) throws IOException {
                if (++bytes > MAX_BYTES) throw new CsvExportLimitException("Export exceeds maxBytes");
                out.write(value);
            }
            @Override public void write(byte[] bytes, int offset, int length) throws IOException {
                if ((this.bytes += length) > MAX_BYTES) throw new CsvExportLimitException("Export exceeds maxBytes");
                out.write(bytes, offset, length);
            }
        };
        BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(bounded, StandardCharsets.UTF_8), 16_384);
        writeRecord(writer, HEADERS);
        rowSource.stream(platform, revision.id(), row -> {
            if (++rows[0] > MAX_ROWS) throw new CsvExportLimitException("Export exceeds maxRows; narrow the requested dataset");
            if (System.nanoTime() - started > MAX_DURATION.toNanos()) throw new CsvExportLimitException("Export exceeds maxDuration");
            writeRecord(writer, values(row, revision.id()));
        });
        writer.flush();
    }

    public static List<String> values(PublicationCsvRow row, long revision) {
        return List.of(
                text(row.platform()),
                text(row.institution()),
                text(row.publicationId()),
                text(row.publishedAt()),
                text(row.observedAt()),
                text(row.viewsCount()),
                text(row.reactionsCount()),
                text(row.commentsCount()),
                text(row.sharesCount()),
                text(row.quality()),
                Long.toString(revision)
        );
    }

    private static String text(Object value) {
        return value == null ? "" : value.toString();
    }

    public static void writeRecord(BufferedWriter writer, List<String> values) throws IOException {
        for (int index = 0; index < values.size(); index++) {
            if (index > 0) {
                writer.write(',');
            }
            String value = neutralizeSpreadsheetFormula(values.get(index));
            boolean quoted = value.indexOf(',') >= 0 || value.indexOf('"') >= 0
                    || value.indexOf('\n') >= 0 || value.indexOf('\r') >= 0;
            if (quoted) {
                writer.write('"');
            }
            for (int character = 0; character < value.length(); character++) {
                char current = value.charAt(character);
                if (current == '"') {
                    writer.write("\"\"");
                } else {
                    writer.write(current);
                }
            }
            if (quoted) {
                writer.write('"');
            }
        }
        writer.write("\r\n");
    }

    private static String neutralizeSpreadsheetFormula(String value) {
        if (value.isEmpty()) {
            return value;
        }
        int start=0;
        while(start<value.length()&&(Character.isWhitespace(value.charAt(start))||Character.isISOControl(value.charAt(start))))start++;
        if(start==value.length())return value;
        return switch (value.charAt(start)) {
            case '=', '+', '-', '@' -> "'" + value;
            default -> value;
        };
    }
}
