package org.mranked.legacyexport.application;

import java.io.IOException;
import java.util.List;

public interface LegacyCsvRows {
    void stream(LegacyCsvFormat format, long revision, RowConsumer consumer) throws IOException;
    @FunctionalInterface interface RowConsumer {void accept(List<String> cells) throws IOException;}
}
