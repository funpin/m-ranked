package org.mranked.admin.application;
import java.util.UUID;
import org.springframework.stereotype.Service;
@Service
public class OfficialRatingService {
    private final OfficialRatingSource source;
    private final OfficialRatingRepository repository;
    public OfficialRatingService(OfficialRatingSource source,OfficialRatingRepository repository) { this.source=source;this.repository=repository; }
    public OfficialRatingRepository.Result refresh(String actor,UUID correlation) {
        String principal=AdminService.sanitizeActor(actor);
        if(correlation==null) throw new IllegalArgumentException("Correlation ID is required");
        var previous=repository.previous(principal,correlation);
        if(previous.isPresent()) return previous.orElseThrow();
        org.mranked.admin.domain.OfficialRatingDataset dataset;
        try { dataset=source.fetch(); }
        catch(RuntimeException failure) { repository.recordFailure(principal,correlation,"official_source_unavailable"); throw failure; }
        return repository.persist(dataset,principal,correlation);
    }
}
