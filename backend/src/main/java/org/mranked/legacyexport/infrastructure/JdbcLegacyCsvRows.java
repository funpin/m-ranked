package org.mranked.legacyexport.infrastructure;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.sql.ResultSet;
import java.util.Arrays;
import javax.sql.DataSource;
import org.mranked.legacyexport.application.LegacyCsvFormat;
import org.mranked.legacyexport.application.LegacyCsvRows;
import org.mranked.legacyexport.application.LegacyCsvService;
import org.mranked.legacyexport.application.LegacyCsvUnavailable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcLegacyCsvRows implements LegacyCsvRows {
    private final JdbcTemplate jdbc;
    private static final String FILTER = "dataset_revision_id=? AND kind=? AND namespace=? AND (?='all' OR platform::text=?)";
    public JdbcLegacyCsvRows(DataSource source) {jdbc = new JdbcTemplate(source);}
    @Override public void stream(LegacyCsvFormat format, long revision, RowConsumer consumer) throws IOException {
        Boolean ready = jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM analytics.projection_state WHERE projection_name='legacy_exports' "
            + "AND status='ready' AND dataset_revision_id=?)", Boolean.class, revision);
        if (!Boolean.TRUE.equals(ready)) {
            if (revision == 0 && Boolean.TRUE.equals(jdbc.queryForObject(
                    "SELECT NOT EXISTS(SELECT 1 FROM ingest.visible_publication LIMIT 1)", Boolean.class))) return;
            throw new LegacyCsvUnavailable("PROJECTION_NOT_READY");
        }
        var problems = jdbc.queryForList("SELECT blocked_reason FROM analytics.legacy_export_row WHERE " + FILTER
            + " AND blocked_reason IS NOT NULL ORDER BY ordinal LIMIT 1", String.class,
            revision, format.kind(), format.namespace(), format.platform(), format.platform());
        if (!problems.isEmpty()) throw new LegacyCsvUnavailable(problems.getFirst());
        try {
            jdbc.query(connection -> {
                var statement = connection.prepareStatement("SELECT cells FROM analytics.legacy_export_row WHERE " + FILTER
                    + " ORDER BY ordinal LIMIT ?", ResultSet.TYPE_FORWARD_ONLY, ResultSet.CONCUR_READ_ONLY);
                statement.setFetchDirection(ResultSet.FETCH_FORWARD);
                statement.setFetchSize(500);
                statement.setQueryTimeout(300);
                statement.setLong(1, revision);
                statement.setString(2, format.kind()); statement.setString(3, format.namespace());
                statement.setString(4, format.platform()); statement.setString(5, format.platform());
                statement.setLong(6, LegacyCsvService.MAX_ROWS + 1);
                return statement;
            }, row -> {
                var cells = row.getArray("cells");
                try {consumer.accept(Arrays.asList((String[]) cells.getArray()));}
                catch (IOException failure) {throw new UncheckedIOException(failure);}
                finally {cells.free();}
            });
        } catch (UncheckedIOException failure) {throw failure.getCause();}
    }
}
