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

    @Test void neutralizesFormulaPrefixesAfterSpreadsheetIgnoredWhitespace() throws Exception {
        var output=new ByteArrayOutputStream();
        var writer=new BufferedWriter(new OutputStreamWriter(output,StandardCharsets.UTF_8));
        CsvExportService.writeRecord(writer,List.of("\t=1+1","  +1","\r@SUM(A1:A2)"," ordinary"));writer.flush();
        assertThat(output.toString(StandardCharsets.UTF_8)).isEqualTo("'\t=1+1,'  +1,\"'\r@SUM(A1:A2)\", ordinary\r\n");
    }
    @Test
    void maxRowsAreEnforcedWithoutMaterializingTheExportAndSlotsRecover() throws Exception {
        java.util.concurrent.atomic.AtomicInteger count = new java.util.concurrent.atomic.AtomicInteger();
        PublicationCsvRow row = new PublicationCsvRow("vk", "large", UUID.randomUUID(), Instant.EPOCH,
                Instant.EPOCH, 0L, null, null, null, "exact");
        CsvExportService service = new CsvExportService((platform,revision,consumer)-> {
            for (int index=0; index<=CsvExportService.MAX_ROWS; index++) {
                count.incrementAndGet();consumer.accept(row);
            }
        }, ()->new DatasetRevision(5,Instant.EPOCH));
        for (int attempt=0;attempt<3;attempt++) {
            org.assertj.core.api.Assertions.assertThatThrownBy(()->service.prepare(Platform.VK))
                    .isInstanceOf(CsvExportLimitException.class).hasMessageContaining("maxRows");
        }
        assertThat(count.get()).isEqualTo(3*(CsvExportService.MAX_ROWS+1));
        service.shutdown();
    }

    @Test
    void disconnectDeletesTheSpoolAndReleasesDownloadCapacity() throws Exception {
        CsvExportService service = new CsvExportService((platform,revision,consumer)-> {},
                ()->new DatasetRevision(7,Instant.EPOCH));
        var artifact = service.prepare(Platform.ALL);
        assertThat(java.nio.file.Files.exists(artifact.path())).isTrue();
        org.assertj.core.api.Assertions.assertThatThrownBy(()->artifact.transferTo(new java.io.OutputStream() {
            @Override public void write(int value) throws java.io.IOException { throw new java.io.IOException("client disconnected"); }
        })).isInstanceOf(java.io.IOException.class).hasMessageContaining("disconnected");
        assertThat(java.nio.file.Files.exists(artifact.path())).isFalse();
        assertThat(artifact.slots().availablePermits()).isEqualTo(4);
        artifact.close();
        assertThat(artifact.slots().availablePermits()).isEqualTo(4);
        service.shutdown();
    }

    @Test
    void rateLimitStopsAnonymousRepeatedWorkBeforeOpeningDatabaseCursor() throws Exception {
        java.util.concurrent.atomic.AtomicInteger opened = new java.util.concurrent.atomic.AtomicInteger();
        CsvExportService service = new CsvExportService((platform,revision,consumer)->opened.incrementAndGet(),
                ()->new DatasetRevision(7,Instant.EPOCH));
        for(int index=0;index<10;index++) try(var artifact=service.prepare(Platform.ALL)) { }
        org.assertj.core.api.Assertions.assertThatThrownBy(()->service.prepare(Platform.ALL))
                .isInstanceOf(CsvExportLimitException.class).hasMessageContaining("rate limit");
        assertThat(opened).hasValue(10);
        service.shutdown();
    }
}
