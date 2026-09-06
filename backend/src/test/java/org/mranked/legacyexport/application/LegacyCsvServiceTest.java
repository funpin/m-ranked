package org.mranked.legacyexport.application;

import static org.assertj.core.api.Assertions.*;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.StringWriter;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mranked.cache.domain.DatasetRevision;

class LegacyCsvServiceTest {
    @Test void sixHundredThousandRowsStreamWithSixtyFourMiBHeap() throws Exception {
        String executable=java.nio.file.Path.of(System.getProperty("java.home"),"bin","java").toString();
        var process=new ProcessBuilder(executable,"-Xmx64m","-cp",System.getProperty("java.class.path"),LegacyCsvHeapProbe.class.getName())
            .redirectErrorStream(true).start();
        assertThat(process.waitFor(30,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
        String result=new String(process.getInputStream().readAllBytes(),java.nio.charset.StandardCharsets.UTF_8);
        assertThat(process.exitValue()).withFailMessage(result).isZero();
        assertThat(result).contains("\"rows\":600000","\"heapMaxBytes\":67108864");
        var report=java.nio.file.Path.of(System.getProperty("mranked.build.directory","target"),"legacy-csv-heap.json");
        java.nio.file.Files.writeString(report,result);
    }
    @Test void frozenPythonDialectRetainsFormulaNegativeNullUnicodeAndCrlfWithoutBom() throws Exception {
        var writer = new StringWriter();
        LegacyCsvFormat.writeRecord(writer, Arrays.asList("=formula", "-2", "0", null, "@name", "a,\"b\"\r\nЮ"));
        assertThat(writer.toString()).isEqualTo("=formula,-2,0,,@name,\"a,\"\"b\"\"\r\nЮ\"\r\n");
        assertThat(new LegacyCsvFormat("posts", " TG ").filename()).isEqualTo("posts.csv");
        assertThat(new LegacyCsvFormat("snapshots", "ОБЩИЙ").filename()).isEqualTo("snapshots-all.csv");
        assertThat(new LegacyCsvFormat("posts", "unknown").platform()).isEqualTo("telegram");
        assertThat(new LegacyCsvFormat("posts", "\u00a0 VK \u0085").platform()).isEqualTo("vk");
    }
    @Test void classifiedFailureNeverCommitsAnArtifactAndDisconnectRemovesTheCompletedSpool() throws Exception {
        var revision = new DatasetRevision(29, Instant.parse("2026-08-01T12:00:00Z"));
        var failed = new LegacyCsvService((format, id, consumer) -> {throw new LegacyCsvUnavailable("UNSAFE_RAW_JSON");}, () -> revision);
        try {assertThatThrownBy(() -> failed.prepare(new LegacyCsvFormat("posts", "vk"))).isInstanceOf(LegacyCsvUnavailable.class);}
        finally {failed.close();}
        var service = new LegacyCsvService((format, id, consumer) -> consumer.accept(Arrays.asList("tg", "1", "time", "1", "0", null, "0", "-2", "1.0")), () -> revision);
        try {
            var artifact = service.prepare(new LegacyCsvFormat("posts", "telegram"));
            assertThat(artifact.revision()).isEqualTo(revision);
            assertThatThrownBy(() -> artifact.transferTo(new java.io.OutputStream() {
                @Override public void write(int value) throws IOException {throw new IOException("disconnect");}
            })).isInstanceOf(IOException.class);
            assertThat(artifact.path()).doesNotExist();
        } finally {service.close();}
    }
    @Test void rowOverflowRejectsInsteadOfSilentlyTruncating() {
        var cells = Arrays.asList("tg", "1", "time", "1", "0", null, "0", "-2", "1.0");
        var service = new LegacyCsvService((format, id, consumer) -> {
            for (int i = 0; i <= LegacyCsvService.MAX_ROWS; i++) consumer.accept(cells);
        }, () -> new DatasetRevision(1, Instant.EPOCH));
        try {assertThatThrownBy(() -> service.write(new LegacyCsvFormat("posts", "telegram"), 1, java.io.OutputStream.nullOutputStream()))
            .isInstanceOf(org.mranked.query.application.CsvExportLimitException.class).hasMessageContaining("maxRows");}
        finally {service.close();}
    }
}
