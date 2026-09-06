package org.mranked.admin.domain;
import java.time.Instant;
import java.util.Map;
public record OfficialRatingDataset(String period,Map<String,Map<String,OfficialRating>> rankings,
        String sourceUrl,String sourceSha256,Instant fetchedAt,Map<String,Object> evidence) { }
