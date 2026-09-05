package org.mranked.query.application;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.BufferedWriter;
import java.io.ByteArrayOutputStream;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.mranked.analytics.domain.Platform;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.query.domain.PublicationCsvRow;

class CsvExportServiceTest {
    @Test
    void writesRowsIncrementallyWithRfc4180EscapingAndNullableCounters() throws Exception {
        AtomicInteger consumed = new AtomicInteger();
        PublicationCsvRowSource source = (platform, revision, consumer) -> {
            assertThat(platform).isEqualTo(Platform.TELEGRAM);
            assertThat(revision).isEqualTo(31);
            consumer.accept(new PublicationCsvRow(
                    "telegram", "University, \"North\"\nCampus",
                    UUID.fromString("00000000-0000-0000-0000-000000000101"),
                    Instant.parse("2026-09-01T10:00:00Z"),
                    Instant.parse("2026-09-03T10:00:00Z"),
                    100L, null, 4L, 2L, "observed"
            ));
            consumed.incrementAndGet();
            consumer.accept(new PublicationCsvRow(
                    "telegram", "Second",
                    UUID.fromString("00000000-0000-0000-0000-000000000102"),
                    Instant.parse("2026-09-01T11:00:00Z"),
                    Instant.parse("2026-09-03T11:00:00Z"),
                    0L, 0L, 0L, 0L, "exact"
            ));
            consumed.incrementAndGet();
        };
        DatasetRevisionProvider revisions = () -> new DatasetRevision(31, Instant.EPOCH);
        CsvExportService service = new CsvExportService(source, revisions);
        ByteArrayOutputStream output = new ByteArrayOutputStream();

        service.write(
                Platform.TELEGRAM,
                new DatasetRevision(31, Instant.parse("2026-09-03T12:00:00Z")),
                output
        );

        String csv = output.toString(StandardCharsets.UTF_8);
        assertThat(consumed).hasValue(2);
        assertThat(csv).startsWith(
                "platform,institution,publication_id,published_at,observed_at,views,reactions,comments,shares,quality,dataset_revision\r\n"
        );
        assertThat(csv).contains("\"University, \"\"North\"\"\nCampus\"");
        assertThat(csv).contains(",100,,4,2,observed,31\r\n");
        assertThat(csv).endsWith(",0,0,0,0,exact,31\r\n");
        assertThat(csv).doesNotStartWith("\ufeff");
    }

    @Test
    void neutralizesEveryDangerousSpreadsheetFormulaPrefixBeforeCsvEscaping() throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(output, StandardCharsets.UTF_8));

        CsvExportService.writeRecord(writer, List.of(
                "=1+1",
                "+1+1",
                "-1+1",
                "@SUM(A1:A2)",
                "=HYPERLINK(\"https://example.invalid\",\"open\")",
                "ordinary",
                ""
        ));
        writer.flush();

        assertThat(output.toString(StandardCharsets.UTF_8)).isEqualTo(
                "'=1+1,'+1+1,'-1+1,'@SUM(A1:A2),"
                        + "\"'=HYPERLINK(\"\"https://example.invalid\"\",\"\"open\"\")\",ordinary,\r\n"
        );
    }
}
