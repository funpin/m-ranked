package org.mranked.query.infrastructure;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.UUID;
import javax.sql.DataSource;
import org.mranked.analytics.domain.Platform;
import org.mranked.query.application.PublicationCsvRowSource;
import org.mranked.query.domain.PublicationCsvRow;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

@Repository
public class JdbcPublicationCsvRowSource implements PublicationCsvRowSource {
    static final int FETCH_SIZE = 500;
    static final String EXPORT_SQL = """
            SELECT latest.platform::text AS platform,
                   institution.canonical_name AS institution,
                   publication.id AS publication_id,
                   publication.published_at,
                   latest.observed_at,
                   latest.views_count,
                   latest.reactions_count,
                   latest.comments_count,
                   latest.shares_count,
                   latest.quality::text AS quality
            FROM analytics.publication_latest latest
            JOIN ingest.visible_publication publication ON publication.id = latest.publication_id
            JOIN catalog.visible_institution institution ON institution.id = latest.institution_id
            WHERE latest.dataset_revision_id = ?
              AND (? = 'all' OR latest.platform::text = ?)
            ORDER BY publication.published_at, publication.id
            LIMIT ?
            """;

    private final JdbcTemplate jdbcTemplate;

    public JdbcPublicationCsvRowSource(DataSource dataSource) {
        this.jdbcTemplate = new JdbcTemplate(dataSource);
    }

    @Override
    @Transactional(readOnly = true, isolation = org.springframework.transaction.annotation.Isolation.REPEATABLE_READ, timeout = 30)
    public void stream(
            Platform platform,
            long datasetRevision,
            CsvRowConsumer consumer
    ) throws IOException {
        streamBounded(platform, datasetRevision, 100_000, 30, consumer);
    }

    @Override
    @Transactional(readOnly = true, isolation = org.springframework.transaction.annotation.Isolation.REPEATABLE_READ, timeout = 300)
    public void streamBounded(Platform platform, long datasetRevision, long maxRows,
                              int timeoutSeconds, CsvRowConsumer consumer) throws IOException {
        if (maxRows < 1 || maxRows > 2_000_000 || timeoutSeconds < 1 || timeoutSeconds > 300) {
            throw new IllegalArgumentException("Invalid bounded export policy");
        }
        try {
            jdbcTemplate.query(connection -> {
                var statement = connection.prepareStatement(
                        EXPORT_SQL,
                        ResultSet.TYPE_FORWARD_ONLY,
                        ResultSet.CONCUR_READ_ONLY
                );
                statement.setFetchDirection(ResultSet.FETCH_FORWARD);
                statement.setFetchSize(FETCH_SIZE);
                statement.setQueryTimeout(timeoutSeconds);
                statement.setLong(1, datasetRevision);
                statement.setString(2, platform.databaseValue());
                statement.setString(3, platform.databaseValue());
                statement.setLong(4, maxRows + 1);
                return statement;
            }, resultSet -> {
                try {
                    consumer.accept(row(resultSet));
                } catch (IOException exception) {
                    throw new UncheckedIOException(exception);
                }
            });
        } catch (UncheckedIOException exception) {
            throw exception.getCause();
        }
    }

    private static PublicationCsvRow row(ResultSet resultSet) throws SQLException {
        return new PublicationCsvRow(
                resultSet.getString("platform"),
                resultSet.getString("institution"),
                resultSet.getObject("publication_id", UUID.class),
                instant(resultSet, "published_at"),
                instant(resultSet, "observed_at"),
                resultSet.getObject("views_count", Long.class),
                resultSet.getObject("reactions_count", Long.class),
                resultSet.getObject("comments_count", Long.class),
                resultSet.getObject("shares_count", Long.class),
                resultSet.getString("quality")
        );
    }

    private static Instant instant(ResultSet resultSet, String column) throws SQLException {
        OffsetDateTime value = resultSet.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }
}
