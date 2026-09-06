package org.mranked.exportjob.application;

import java.io.BufferedWriter;
import java.io.FilterOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CancellationException;
import org.mranked.analytics.domain.Platform;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.query.application.CsvExportService;
import org.mranked.query.application.PublicationCsvRowSource;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Component
public class ExportJobGenerator {
    public interface Progress {
        boolean cancelled();
        void rows(long rows);
        void bytes(long bytes);
    }

    private final DatasetRevisionProvider revisions;
    private final PublicationCsvRowSource rows;

    public ExportJobGenerator(DatasetRevisionProvider revisions, PublicationCsvRowSource rows) {
        this.revisions = revisions;
        this.rows = rows;
    }

    // Revision validation and every cursor fetch use this one MVCC snapshot.
    // A queued job whose revision was replaced fails visibly rather than
    // producing an empty or mixed-revision file.
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, timeout = 300)
    public void generate(Platform platform, long revision, ExportJobPolicy policy,
                         OutputStream output, Progress progress) throws IOException {
        long started = System.nanoTime();
        if (revisions.current().id() != revision) throw new ExportJobFailure(ExportJobFailure.Code.REVISION_CHANGED);
        long[] rowCount = {0};
        OutputStream bounded = new FilterOutputStream(output) {
            private long bytes;
            private void before(int amount) {
                check(progress, started, policy);
                if (amount > policy.maxBytes() - bytes) throw new ExportJobFailure(ExportJobFailure.Code.MAX_BYTES);
            }
            @Override public void write(int value) throws IOException {
                before(1); out.write(value); progress.bytes(++bytes);
            }
            @Override public void write(byte[] value, int offset, int length) throws IOException {
                before(length); out.write(value, offset, length); bytes += length; progress.bytes(bytes);
            }
        };
        BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(bounded, StandardCharsets.UTF_8), 16_384);
        CsvExportService.writeRecord(writer, CsvExportService.HEADERS);
        rows.streamBounded(platform, revision, policy.maxRows(),
                Math.max(1, (int) policy.maxDuration().toSeconds()), row -> {
                    check(progress, started, policy);
                    if (rowCount[0] >= policy.maxRows()) throw new ExportJobFailure(ExportJobFailure.Code.MAX_ROWS);
                    CsvExportService.writeRecord(writer, CsvExportService.values(row, revision));
                    progress.rows(++rowCount[0]);
                });
        check(progress, started, policy);
        writer.flush();
    }

    private static void check(Progress progress, long started, ExportJobPolicy policy) {
        if (progress.cancelled() || Thread.currentThread().isInterrupted()) throw new CancellationException();
        if (System.nanoTime() - started >= policy.maxDuration().toNanos()) {
            throw new ExportJobFailure(ExportJobFailure.Code.MAX_DURATION);
        }
    }
}
