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
    static final List<String> HEADERS = List.of(
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
        BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(output, StandardCharsets.UTF_8), 16_384);
        writeRecord(writer, HEADERS);
        rowSource.stream(platform, revision.id(), row -> writeRecord(writer, values(row, revision.id())));
        writer.flush();
    }

    private static List<String> values(PublicationCsvRow row, long revision) {
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

    static void writeRecord(BufferedWriter writer, List<String> values) throws IOException {
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
        return switch (value.charAt(0)) {
            case '=', '+', '-', '@' -> "'" + value;
            default -> value;
        };
    }
}
