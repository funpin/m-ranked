package org.mranked.query.application;

import java.io.IOException;
import org.mranked.analytics.domain.Platform;
import org.mranked.query.domain.PublicationCsvRow;

public interface PublicationCsvRowSource {
    void stream(Platform platform, long datasetRevision, CsvRowConsumer consumer) throws IOException;

    default void streamBounded(Platform platform, long datasetRevision, long maxRows,
                               int timeoutSeconds, CsvRowConsumer consumer) throws IOException {
        stream(platform, datasetRevision, consumer);
    }

    @FunctionalInterface
    interface CsvRowConsumer {
        void accept(PublicationCsvRow row) throws IOException;
    }
}
