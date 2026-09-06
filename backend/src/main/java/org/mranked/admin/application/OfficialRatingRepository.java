package org.mranked.admin.application;
import java.util.Optional;
import java.util.UUID;
import org.mranked.admin.domain.OfficialRatingDataset;
public interface OfficialRatingRepository {
    record Result(String period,int updated,int available,String fetchedAt,Long datasetRevision) { }
    Optional<Result> previous(String actor,UUID correlation);
    Result persist(OfficialRatingDataset dataset,String actor,UUID correlation);
    void recordFailure(String actor,UUID correlation,String errorCode);
}
