package org.mranked.analysis.application;

import java.util.UUID;
import org.mranked.analysis.domain.PublicationAnalysis;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.query.application.ResourceNotFoundException;
import org.springframework.stereotype.Service;

@Service
public class AnalysisService {
    private final AnalysisQueryPort queries;
    private final DatasetRevisionProvider datasetRevision;

    public AnalysisService(AnalysisQueryPort queries, DatasetRevisionProvider datasetRevision) {
        this.queries = queries;
        this.datasetRevision = datasetRevision;
    }

    public PublicationAnalysis get(String id, String legacyType, int limit, String cursor) {
        if (limit < 1 || limit > 100
                || !("posts".equals(legacyType) || "platform_posts".equals(legacyType))
                || (cursor != null && cursor.length() > 512)) {
            throw new IllegalArgumentException("invalid anomaly analysis query");
        }
        UUID publication = queries.resolvePublication(id, legacyType)
                .orElseThrow(() -> new ResourceNotFoundException("publication not found"));
        AnalysisSnapshot head = queries.load(publication, 0, null);
        UUID after = AnalysisCursor.decode(cursor, publication, head.analysisRevision(), limit);
        AnalysisSnapshot snapshot = queries.load(publication, limit, after);
        if (snapshot.analysisRevision() != head.analysisRevision()) {
            throw new org.mranked.query.application.InvalidCursorException();
        }
        String next = snapshot.continuationId() == null ? null
                : AnalysisCursor.encode(publication, snapshot.analysisRevision(), limit, snapshot.continuationId());
        return new PublicationAnalysis(
                publication, datasetRevision.current().id(), snapshot.analysisRevision(), snapshot.sourceDatasetRevision(),
                snapshot.analyzedAt(), snapshot.status(), snapshot.sourceRevisionAt(), snapshot.suspicionScore(),
                snapshot.overallSeverity(), snapshot.manualAssessmentPresent(), snapshot.affectedMetrics(),
                snapshot.activeFindingCount(), snapshot.findings(), next,
                PublicationAnalysis.METHODOLOGY_VERSION, PublicationAnalysis.DISCLAIMER
        );
    }
}
