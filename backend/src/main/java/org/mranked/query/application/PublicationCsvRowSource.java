package org.mranked.query.application;

import java.io.IOException;
import org.mranked.analytics.domain.Platform;
import org.mranked.query.domain.PublicationCsvRow;

public interface PublicationCsvRowSource {
    void stream(Platform platform, long datasetRevision, CsvRowConsumer consumer) throws IOException;

    @FunctionalInterface
    interface CsvRowConsumer {
        void accept(PublicationCsvRow row) throws IOException;
    }
}
